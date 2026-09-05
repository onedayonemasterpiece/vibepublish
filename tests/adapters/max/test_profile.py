import importlib
import multiprocessing
import os
from pathlib import Path

import pytest

module = importlib.import_module('adapters.max.profile')
ProfileLane, MaxBlocked = module.ProfileLane, module.MaxBlocked


def claim(root, connection, arm=False):
    try:
        with ProfileLane(Path(root)) as lane:
            if arm:
                lane.arm('attempt', 'digest')
            connection.send('owned')
            connection.recv()
    except MaxBlocked as exc:
        connection.send(str(exc))


def test_M11_real_process_claim_and_crash_quarantine(tmp_path):
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe()
    profile = tmp_path/'profile'
    proc = context.Process(target=claim, args=(str(profile), child, True))
    proc.start()
    try:
        assert parent.poll(10) and parent.recv() == 'owned'
        with pytest.raises(MaxBlocked, match='profile_busy'):
            with ProfileLane(profile):
                pass
        proc.kill()
        proc.join(10)
        with ProfileLane(profile) as lane:
            with pytest.raises(MaxBlocked, match='outcome_unknown'):
                lane.arm('NEW-operation', 'NEW-plan')
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join()
        parent.close()
        child.close()


def test_permissions_symlink_and_no_lock_unlink(tmp_path):
    profile = tmp_path/'profile'
    with ProfileLane(profile):
        inode = (profile/'.vibepublish.lock').stat().st_ino
    with ProfileLane(profile):
        assert (profile/'.vibepublish.lock').stat().st_ino == inode
    alias = tmp_path/'alias'
    alias.symlink_to(profile)
    with pytest.raises(MaxBlocked, match='unsafe_profile_path'):
        with ProfileLane(alias):
            pass
    os.chmod(profile, 0o755)
    with pytest.raises(MaxBlocked, match='profile_permissions'):
        with ProfileLane(profile):
            pass


def test_lane_required_and_durable_marker(tmp_path):
    lane = ProfileLane(tmp_path/'profile')
    with pytest.raises(MaxBlocked, match='profile_not_owned'):
        lane.arm('attempt', 'digest')
    with lane:
        lane.arm('attempt', 'digest')
        assert lane.marker.stat().st_mode & 0o777 == 0o600
        with pytest.raises(MaxBlocked, match='outcome_unknown'):
            lane.assert_clear()
        lane.resolve_observed()
        lane.assert_clear()
