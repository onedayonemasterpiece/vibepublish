"""Typed image-job executor boundary; no social credentials in image requests.

Default wiring is unavailable. The owner-authorized ordinary Codex-task route is
in codex_task_imagegen.py; the legacy opt-in transport is in codex_imagegen.py. The fake is a durable,
explicit offline fixture, not a claim of model generation. Its remote job files
simulate an external executor, never a second publication/business ledger.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from PIL import Image
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest


@dataclass(frozen=True, slots=True)
class ImagegenSource:
    asset_ref: str
    sha256: str
    mime: str
    width: int
    height: int
    size: int
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ImagegenRequest:
    job_key: str
    input_digest: str
    mode: Literal['generate', 'tune', 'compose']
    brief: str
    sources: tuple[ImagegenSource, ...]
    preset_version: str
    requested_route: str
    candidate_budget: int
    deadline: float

    def __post_init__(self):
        object.__setattr__(self, 'sources', tuple(self.sources))


@dataclass(frozen=True, slots=True)
class ImagegenArtifact:
    ref: str = field(repr=False)
    sha256: str
    mime: str
    width: int
    height: int
    size: int


@dataclass(frozen=True, slots=True)
class ImagegenObservation:
    job_key: str
    input_digest: str
    execution_ref: str
    state: Literal['queued', 'running', 'succeeded', 'failed', 'unknown']
    artifacts: tuple[ImagegenArtifact, ...] = ()
    actual_executor: str | None = None
    actual_model: str | None = None
    usage_json: str = '{}'
    fixture: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'artifacts', tuple(self.artifacts))


class ImagegenExecutor(Protocol):
    artifact_root: Path
    async def submit(self, request: ImagegenRequest) -> str: ...
    async def inspect(self, execution_ref: str) -> ImagegenObservation: ...
    async def find(self, job_key: str) -> ImagegenObservation | None: ...
    async def cancel(self, execution_ref: str) -> ImagegenObservation: ...


class UnavailableImagegen:
    artifact_root = Path('/nonexistent/vibepublish-imagegen')
    async def submit(self, request):
        raise DomainError('imagegen_not_configured', 'The real $imagegen route is not connected', 'contact_owner')
    async def inspect(self, execution_ref):
        raise OutcomeUnknown('imagegen_observation_unavailable')
    async def find(self, job_key):
        raise OutcomeUnknown('imagegen_observation_unavailable')
    async def cancel(self, execution_ref):
        raise DomainError('imagegen_not_configured', next_action='contact_owner')


class FakeImagegen:
    """Deterministic tiny art-only PNGs; explicit request/actual identity separation."""
    def __init__(self, root: Path, *, fail=False, lost_response=False):
        self.artifact_root = Path(root).absolute()
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fail, self.lost_response = fail, lost_response
        self.calls: list[ImagegenRequest] = []

    def _path(self, job_key):
        if not re.fullmatch(r'visual_[a-f0-9]{32}', job_key):
            raise DomainError('imagegen_job_key_invalid')
        return self.artifact_root/(job_key + '.json')

    async def submit(self, request):
        self.calls.append(request)
        path = self._path(request.job_key)
        if path.exists():
            old = await self.find(request.job_key)
            if old.input_digest != request.input_digest:
                raise DomainError('imagegen_idempotency_conflict')
            return old.execution_ref
        if not 1 <= request.candidate_budget <= 4:
            raise DomainError('imagegen_budget_invalid')
        for source in request.sources:
            if len(source.data) != source.size or hashlib.sha256(source.data).hexdigest() != source.sha256:
                raise DomainError('imagegen_source_integrity')
        artifacts = []
        output_root = self.artifact_root/request.job_key
        output_root.mkdir(mode=0o700, exist_ok=True)
        if not self.fail:
            for ordinal in range(request.candidate_budget):
                color = tuple(bytes.fromhex(digest([request.input_digest, ordinal]))[:3])
                image = Image.new('RGB', (128, 160), color)
                stream = io.BytesIO(); image.save(stream, format='PNG'); data = stream.getvalue()
                ref = f'{ordinal}.png'
                target = output_root/ref
                # Exclusive files + atomic manifest emulate a provider's durable job.
                with target.open('xb') as output:
                    output.write(data); output.flush(); os.fsync(output.fileno())
                artifacts.append(ImagegenArtifact(ref, hashlib.sha256(data).hexdigest(), 'image/png', 128, 160, len(data)))
        result = ImagegenObservation(request.job_key, request.input_digest, request.job_key,
            'failed' if self.fail else 'succeeded', tuple(artifacts), 'fake-imagegen-v1', None,
            canonical({'art_candidates': len(artifacts)}), True)
        temp = path.with_name(path.name+'.'+secrets.token_hex(4)+'.tmp')
        with temp.open('x') as output:
            output.write(canonical(asdict(result))); output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
        if self.lost_response:
            raise OSError('Simulated lost executor response')
        return result.execution_ref

    async def find(self, job_key):
        path = self._path(job_key)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        data['artifacts'] = tuple(ImagegenArtifact(**item) for item in data['artifacts'])
        return ImagegenObservation(**data)

    async def inspect(self, execution_ref):
        result = await self.find(execution_ref)
        if result is None:
            raise OutcomeUnknown('imagegen_job_not_observed')
        return result

    async def cancel(self, execution_ref):
        # These fixtures finish at submit; cancellation cannot erase existing output.
        return await self.inspect(execution_ref)
