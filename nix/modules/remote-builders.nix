{ lib, config, ... }:
let
  builderLib = import ../lib.nix { inherit lib; };
  cfg = config.builder.remoteBuilders;
in
{
  options.builder.remoteBuilders = {
    enable = lib.mkEnableOption "remote Nix builders configured through the builder flake";

    useSubstitutes = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether remote builders may use substituters while building.";
    };

    machines = lib.mkOption {
      default = [ ];
      description = "Remote builder definitions to append to nix.buildMachines.";
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            hostName = lib.mkOption {
              type = lib.types.str;
              description = "Remote host name or SSH target.";
            };

            systems = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              description = "System types this machine can build.";
            };

            protocol = lib.mkOption {
              type = lib.types.enum [ "ssh" "ssh-ng" ];
              default = "ssh-ng";
              description = "Transport protocol used by Nix for this builder.";
            };

            sshUser = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Optional SSH user for the remote builder.";
            };

            sshKey = lib.mkOption {
              type = lib.types.nullOr lib.types.path;
              default = null;
              description = "Optional SSH private key path for the remote builder.";
            };

            maxJobs = lib.mkOption {
              type = lib.types.int;
              default = 1;
              description = "Maximum concurrent jobs this machine should receive.";
            };

            speedFactor = lib.mkOption {
              type = lib.types.int;
              default = 1;
              description = "Relative scheduling weight for this machine.";
            };

            supportedFeatures = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Optional features this machine supports.";
            };

            mandatoryFeatures = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Features that must be requested for the machine to be used.";
            };

            publicHostKey = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Optional pinned public host key for the remote builder.";
            };
          };
        }
      );
    };
  };

  config = lib.mkIf cfg.enable {
    nix = builderLib.mkDistributedBuildConfig {
      inherit (cfg) useSubstitutes;
      machines = map builderLib.mkBuildMachine cfg.machines;
    };
  };
}
