"""Explicit bounded local MP4 ingress. No URLs, browser, model, or social effects."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from .domain import DomainError, new_id

MAX_VIDEO_BYTES = 20 * 1024 * 1024
MAX_VIDEO_SECONDS = 120
# Force one local MOV/MP4 demuxer and two declared codecs. External tracks are off.
_INPUT = ['-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
          '-use_absolute_path', '0', '-max_streams', '2', '-codec_whitelist', 'h264,aac',
          '-probesize', str(MAX_VIDEO_BYTES), '-analyzeduration', '5000000']


@dataclass(frozen=True, slots=True)
class VerifiedVideo:
    original: bytes
    data: bytes
    width: int
    height: int
    duration: float


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise DomainError('video_tools_missing', next_action='contact_owner')
    return path


def _run(args, *, timeout, capture=False):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False,
            env={'PATH': os.defpath, 'LANG': 'C', 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired:
        raise DomainError('video_processing_timeout') from None
    except OSError:
        raise DomainError('video_tools_unavailable', next_action='contact_owner') from None
    if result.returncode:
        raise DomainError('invalid_video')
    if capture and len(result.stdout) > 128 * 1024:
        raise DomainError('video_probe_limit')
    return result.stdout if capture else None


def _probe(ffprobe, path):
    raw = _run([ffprobe, '-v', 'error', '-max_alloc', str(64*1024*1024), *_INPUT,
        '-count_packets', '-show_entries', 'format=format_name,duration:stream=codec_type,codec_name,width,height,duration,nb_read_packets:stream_disposition=attached_pic',
        '-of', 'json', '-i', str(path)], timeout=10, capture=True)
    try:
        info = json.loads(raw)
        streams = info['streams']
        videos = [s for s in streams if s['codec_type'] == 'video']
        audios = [s for s in streams if s['codec_type'] == 'audio']
        duration = float(info['format']['duration'])
        if (len(videos) != 1 or len(audios) > 1 or len(streams) != len(videos)+len(audios)
                or videos[0]['codec_name'] != 'h264' or any(s['codec_name'] != 'aac' for s in audios)
                or videos[0].get('disposition', {}).get('attached_pic', 0)):
            raise ValueError()
        width, height = videos[0]['width'], videos[0]['height']
        if (type(width) is not int or type(height) is not int or min(width,height) < 1
                or max(width,height) > 1920 or min(width,height) > 1080
                or not math.isfinite(duration) or not 0 < duration <= MAX_VIDEO_SECONDS):
            raise DomainError('video_limits_exceeded')
        for stream in streams:
            if stream.get('duration') is not None:
                length = float(stream['duration'])
                if not math.isfinite(length) or not 0 < length <= MAX_VIDEO_SECONDS:
                    raise DomainError('video_limits_exceeded')
    except (KeyError, TypeError, ValueError, OverflowError):
        raise DomainError('video_format_unsupported') from None
    try:
        packets = tuple((s['codec_type'], int(s['nb_read_packets'])) for s in streams)
        if any(n <= 0 for _, n in packets):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise DomainError('invalid_video') from None
    return width, height, duration, packets


def verify_video(data: bytes, mime: str, *, artifact_root: Path) -> VerifiedVideo:
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_VIDEO_BYTES:
        raise DomainError('asset_size_limit')
    if mime != 'video/mp4' or len(data) < 12 or data[4:8] != b'ftyp':
        raise DomainError('video_format_unsupported')
    ffprobe, ffmpeg = _tool('ffprobe'), _tool('ffmpeg')
    artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='video-', dir=artifact_root) as temporary:
        root=Path(temporary); source=root/'source.mp4'; output=root/'verified.mp4'
        source.write_bytes(data); source.chmod(0o600)
        width,height,duration,packets = _probe(ffprobe,source)
        # Full bounded decode catches corrupt payloads, not merely plausible headers.
        _run([ffmpeg,'-nostdin','-v','error','-xerror','-max_alloc',str(64*1024*1024),
              '-threads','2',*_INPUT,'-i',str(source),'-map','0:v:0','-map','0:a:0?',
              '-threads','2','-f','null','-'], timeout=30)
        # Container-only sanitized derivative; retain media bytes without a quality conversion.
        _run([ffmpeg,'-nostdin','-v','error','-xerror','-max_alloc',str(64*1024*1024),
              *_INPUT,'-i',str(source),'-map','0:v:0','-map','0:a:0?',
              '-c','copy','-map_metadata','-1','-map_metadata:s','-1','-map_chapters','-1',
              '-movflags','+faststart','-fs',str(MAX_VIDEO_BYTES+1),'-f','mp4',str(output)], timeout=10)
        if not output.exists() or not 0 < output.stat().st_size <= MAX_VIDEO_BYTES:
            raise DomainError('asset_size_limit')
        verified=output.read_bytes()
        actual_width,actual_height,actual_duration,actual_packets = _probe(ffprobe,output)
        if (actual_width,actual_height)!=(width,height) or abs(actual_duration-duration) > .1 or sorted(actual_packets) != sorted(packets):
            raise DomainError('video_identity_changed')
        return VerifiedVideo(data,verified,width,height,actual_duration)


def read_video_file(path: Path) -> bytes:
    """Bounded owner-selected regular file; no FIFO, symlink or URL transport."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        raise DomainError('video_file_unavailable') from None
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise DomainError('video_regular_file_required')
        if not 0 < info.st_size <= MAX_VIDEO_BYTES:
            raise DomainError('asset_size_limit')
        return source.read(MAX_VIDEO_BYTES+1)


def import_video(store, actor, data: bytes, mime: str) -> str:
    # Keep temporary material next to the private ledger, never in public /tmp.
    with store.connection() as db:
        store.current(db, actor)
    video = verify_video(data, mime, artifact_root=store.path.parent/'artifacts'/'video-processing')
    with store.tx() as db:
        store.current(db,actor)
        used=db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?',(actor.tenant_id,)).fetchone()[0]
        quota=db.execute('SELECT storage_limit FROM tenants WHERE id=?',(actor.tenant_id,)).fetchone()[0]
        if used+len(video.original)+len(video.data)>quota:
            raise DomainError('storage_quota_exceeded')
        source_hash=hashlib.sha256(video.original).hexdigest()
        refs=[]
        for payload in (video.original,video.data):
            ref=new_id('asset'); refs.append(ref)
            db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
                (ref,actor.tenant_id,actor.principal_id,hashlib.sha256(payload).hexdigest(),'video/mp4',
                 video.width,video.height,payload,source_hash,store.clock()))
    return refs[-1]
