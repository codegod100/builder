# builder

`builder` is a small Python CLI that makes the remote-build upload step explicit.

Instead of relying on Nix's `ssh-ng` transport, it:

1. Evaluates an installable to its `.drv` path locally.
2. Computes the derivation closure that must exist on the remote machine.
3. Streams that closure with `nix-store --export` over SSH to `nix-store --import`.
4. Shows a byte-based progress bar while the upload is happening.
5. Triggers the remote build with `nix-store --realise`.

## Why this exists

`ssh-ng` remote builders are convenient, but Nix does not expose a real byte progress bar for the upload step. This tool trades some integration for visibility.

## Requirements

- Python 3.11+
- `nix`
- `nix-store`
- `ssh`
- access to the local Nix daemon
- a remote host with `nix-store`

## Install

```bash
cd /home/nandi/code/builder
python3 -m pip install -e .
```

## Reuse From Another Flake

This flake now exposes:

- `packages.<system>.default`: the `builder` CLI
- `overlays.default`: overlay that adds `builder`
- `lib.mkBuildMachine`: helper for normalized `nix.buildMachines` entries
- `lib.mkDistributedBuildConfig`: helper that returns a `nix` config attrset
- `nixosModules.default`: module that enables remote builders on NixOS
- `darwinModules.default`: same module for `nix-darwin`

An input flake cannot silently change how another flake's `nix build` runs. The
consumer has to opt in by importing the module or using the library helpers in
its own Nix configuration.

Example for a NixOS flake:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    builder.url = "path:/home/nandi/code/builder";
  };

  outputs = { self, nixpkgs, builder, ... }: {
    nixosConfigurations.my-host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        builder.nixosModules.default
        ({
          builder.remoteBuilders = {
            enable = true;
            machines = [
              {
                hostName = "builder1.example.com";
                systems = [ "x86_64-linux" "aarch64-linux" ];
                sshUser = "nixremote";
                maxJobs = 8;
                supportedFeatures = [ "kvm" "big-parallel" ];
              }
            ];
          };
        })
      ];
    };
  };
}
```

After that, regular `nix build` on that machine will use the configured remote
builders through the local Nix daemon.

## Shell Notes

The `builder` CLI does not require Bash. It executes `nix`, `nix-store`, and
`ssh` directly. The only shell-sensitive part is how you write command
substitution in your interactive shell when composing installables by hand.

Bash and zsh:

```bash
nix run . -- my-builder .#packages.$(nix eval --impure --raw --expr builtins.currentSystem).default
```

Fish:

```fish
nix run . -- my-builder .#packages.(nix eval --impure --raw --expr builtins.currentSystem).default
```

If you want a shell-agnostic form, resolve the system first and then run the
command with the literal result:

```text
nix eval --impure --raw --expr builtins.currentSystem
# Example output: x86_64-linux
```

```bash
nix run . -- my-builder .#packages.x86_64-linux.default
```

## Usage

Dry-run a plan:

```bash
builder my-builder .#packages.x86_64-linux.default --dry-run
```

Upload and build:

```bash
builder my-builder .#packages.x86_64-linux.default
```

By default, successful remote builds are copied back into the local store. Use
`--no-copy-back` to leave the outputs only on the remote machine.

Use a non-default SSH port:

```bash
builder --ssh-option=-p --ssh-option=2222 my-builder .#hello
```

Upload only:

```bash
builder my-builder .#hello --no-build
```

Build remotely without copying outputs back:

```bash
builder my-builder .#hello --no-copy-back
```

## Notes

- The upload size is estimated from `narSize` metadata for the derivation closure.
- The remote build step currently uses `nix-store --realise` on the imported derivations.
- This is intentionally explicit and low-level. It is closer to `nix-store` plumbing than to `nix build --store ssh-ng://...`.
