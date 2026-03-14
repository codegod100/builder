from __future__ import annotations

import argparse
import json
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Sequence


DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class BuildPlan:
    installables: list[str]
    derivations: list[str]
    outputs: list[str]
    requisites: list[str]
    upload_bytes: int


class BuilderError(RuntimeError):
    """Raised for user-facing CLI failures."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="builder",
        description=(
            "Upload derivation closures to a remote host with a real progress bar, "
            "then trigger a remote build."
        ),
    )
    parser.add_argument("host", help="SSH host used for the remote build")
    parser.add_argument(
        "installables",
        nargs="+",
        help="Nix installables to evaluate and build remotely",
    )
    parser.add_argument(
        "--ssh",
        default="ssh",
        help="SSH executable to use (default: ssh)",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Extra argument passed to the SSH command; repeat as needed",
    )
    parser.add_argument(
        "--nix-option",
        action="append",
        default=[],
        nargs=2,
        metavar=("NAME", "VALUE"),
        help="Extra nix option passed during local evaluation",
    )
    parser.add_argument(
        "--impure",
        action="store_true",
        help="Pass --impure during local evaluation",
    )
    parser.add_argument(
        "--remote-store-command",
        default="nix-store",
        help="Store command to run on the remote host (default: nix-store)",
    )
    parser.add_argument(
        "--copy-back",
        action="store_true",
        help="Copy build outputs back to the local store after the remote build",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Upload the derivation closure but do not trigger the remote build",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate and print the upload/build plan without transferring data",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Streaming chunk size in bytes (default: 1048576)",
    )
    return parser


def nix_base_args(args: argparse.Namespace) -> list[str]:
    base = ["nix"]
    if args.impure:
        base.append("--impure")
    for name, value in args.nix_option:
        base.extend(["--option", name, value])
    return base


def run(
    cmd: Sequence[str],
    *,
    capture_stdout: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(cmd),
            check=True,
            stdout=subprocess.PIPE if capture_stdout else None,
            stderr=subprocess.PIPE,
            text=text,
        )
    except FileNotFoundError as exc:
        raise BuilderError(f"missing executable: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
        raise BuilderError(
            f"command failed ({exc.returncode}): {shell_join(cmd)}\n{stderr.strip()}"
        ) from exc


def shell_join(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def render_progress(current: int, total: int | None, started_at: float) -> str:
    elapsed = max(time.monotonic() - started_at, 0.001)
    rate = current / elapsed
    if total and total > 0:
        width = 28
        ratio = min(current / total, 1.0)
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        eta = int((total - current) / rate) if rate > 0 and current < total else 0
        percent = ratio * 100
        return (
            f"[{bar}] {percent:5.1f}%  "
            f"{format_bytes(current)}/{format_bytes(total)}  "
            f"{format_bytes(int(rate))}/s  eta {eta:>4}s"
        )
    return f"{format_bytes(current)} transferred  {format_bytes(int(rate))}/s"


def ssh_prefix(args: argparse.Namespace) -> list[str]:
    return [args.ssh, *args.ssh_option, args.host]


def evaluate_plan(args: argparse.Namespace) -> BuildPlan:
    base = nix_base_args(args)
    derivation_result = run(
        [*base, "derivation", "show", "--no-pretty", *args.installables]
    )
    derivation_data = json.loads(derivation_result.stdout)
    if not derivation_data:
        raise BuilderError("no derivations were produced by the supplied installables")

    derivations = list(derivation_data.keys())
    outputs = unique(
        output["path"]
        for derivation in derivation_data.values()
        for output in derivation.get("outputs", {}).values()
        if "path" in output
    )

    requisites_result = run(["nix-store", "--query", "--requisites", *derivations])
    requisites = unique(
        [line.strip() for line in requisites_result.stdout.splitlines() if line.strip()]
    )
    size_result = run(["nix", "path-info", "--json", *requisites])
    size_data = json.loads(size_result.stdout)
    upload_bytes = sum(
        int(metadata.get("narSize", 0))
        for metadata in size_data.values()
        if isinstance(metadata, dict)
    )

    return BuildPlan(
        installables=list(args.installables),
        derivations=derivations,
        outputs=outputs,
        requisites=requisites,
        upload_bytes=upload_bytes,
    )


def print_plan(plan: BuildPlan, host: str) -> None:
    print(f"remote host: {host}")
    print(f"installables: {', '.join(plan.installables)}")
    print(f"derivations: {len(plan.derivations)}")
    print(f"closure paths: {len(plan.requisites)}")
    print(f"estimated upload: {format_bytes(plan.upload_bytes)}")
    for drv in plan.derivations:
        print(f"  drv: {drv}")


def stream_upload(args: argparse.Namespace, plan: BuildPlan) -> None:
    remote_import_cmd = [
        *ssh_prefix(args),
        args.remote_store_command,
        "--import",
    ]
    export_cmd = ["nix-store", "--export", *plan.requisites]

    try:
        exporter = subprocess.Popen(export_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise BuilderError("missing executable: nix-store") from exc

    try:
        importer = subprocess.Popen(
            remote_import_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
    except FileNotFoundError as exc:
        exporter.kill()
        raise BuilderError(f"missing executable: {args.ssh}") from exc

    assert exporter.stdout is not None
    assert exporter.stderr is not None
    assert importer.stdin is not None
    assert importer.stderr is not None

    started = time.monotonic()
    transferred = 0

    def stop_process(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)

    try:
        while True:
            chunk = exporter.stdout.read(args.chunk_size)
            if not chunk:
                break
            importer.stdin.write(chunk)
            importer.stdin.flush()
            transferred += len(chunk)
            progress = render_progress(transferred, plan.upload_bytes, started)
            print(f"\r{progress}", end="", file=sys.stderr, flush=True)
        importer.stdin.close()
        print(file=sys.stderr)
    except BrokenPipeError as exc:
        stop_process(exporter)
        stop_process(importer)
        raise BuilderError("remote import process closed early") from exc
    finally:
        exporter.stdout.close()

    export_stderr = exporter.stderr.read().decode().strip()
    import_stderr = importer.stderr.read().decode().strip()
    export_code = exporter.wait()
    import_code = importer.wait()

    if export_code != 0:
        raise BuilderError(
            f"export failed ({export_code}): {shell_join(export_cmd)}\n{export_stderr}"
        )
    if import_code != 0:
        raise BuilderError(
            f"remote import failed ({import_code}): {shell_join(remote_import_cmd)}\n{import_stderr}"
        )


def remote_realise(args: argparse.Namespace, plan: BuildPlan) -> list[str]:
    cmd = [
        *ssh_prefix(args),
        args.remote_store_command,
        "--realise",
        *plan.derivations,
    ]
    result = run(cmd)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def copy_back_outputs(args: argparse.Namespace, outputs: Sequence[str]) -> None:
    if not outputs:
        return
    store_uri = f"ssh://{args.host}"
    copy_cmd = ["nix", "copy", "--from", store_uri, *outputs]
    run(copy_cmd, capture_stdout=False)


def ensure_tools(args: argparse.Namespace) -> None:
    for tool in ("nix", "nix-store", args.ssh):
        if shutil.which(tool) is None:
            raise BuilderError(f"required tool not found in PATH: {tool}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        ensure_tools(args)
        plan = evaluate_plan(args)
        print_plan(plan, args.host)
        if args.dry_run:
            return 0

        stream_upload(args, plan)

        if args.no_build:
            return 0

        outputs = remote_realise(args, plan)
        print("remote outputs:")
        for output in outputs:
            print(output)

        if args.copy_back:
            copy_back_outputs(args, outputs)
        return 0
    except BuilderError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
