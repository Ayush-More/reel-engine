"""Python runner for the local Remotion project."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import ROOT


def render_video(props_path: Path, output_path: Path, *, timeout_s: int = 900,
                 concurrency: int | None = None) -> Path:
    renderer = ROOT / "renderer"
    package_json = renderer / "package.json"
    if not package_json.is_file():
        raise RuntimeError(f"Remotion renderer is missing its package manifest: {package_json}")
    payload = json.loads(props_path.read_text(encoding="utf-8"))
    props = payload["data"] if "data" in payload and "content_hash" in payload else payload
    audio_path = Path(props["audio_path"])
    if not audio_path.is_file():
        raise FileNotFoundError(f"Remotion audio file does not exist: {audio_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_dir = renderer / "public"
    public_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reels-", dir=public_dir) as asset_dir_name:
        asset_dir = Path(asset_dir_name)
        shutil.copyfile(audio_path, asset_dir / audio_path.name)
        props["audio_path"] = f"{asset_dir.name}/{audio_path.name}"
        temp_props = asset_dir / "props.json"
        temp_props.write_text(json.dumps(props), encoding="utf-8")
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to run the local Remotion renderer")
        command = [
            npm, "exec", "--", "remotion", "render", "src/index.ts", "Reel",
            str(output_path.resolve()), f"--props={temp_props.resolve()}",
            "--codec=h264", "--crf=18", "--log=error",
        ]
        if concurrency is not None:
            command.append(f"--concurrency={concurrency}")
        try:
            result = subprocess.run(command, cwd=renderer, capture_output=True, text=True,
                                    timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Remotion render exceeded {timeout_s}s timeout") from exc
        if result.returncode:
            raise RuntimeError(f"Remotion render failed: {(result.stderr or result.stdout)[-4000:]}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Remotion exited successfully without producing a video")
    return output_path
