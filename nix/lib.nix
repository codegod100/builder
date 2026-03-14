{ lib }:
let
  inherit (lib) concatStringsSep filterAttrs optionals removeAttrs;

  compact = attrs: removeAttrs attrs (builtins.attrNames (filterAttrs (_: value: value == null) attrs));
in
{
  mkBuildMachine =
    {
      hostName,
      systems,
      protocol ? "ssh-ng",
      sshUser ? null,
      sshKey ? null,
      maxJobs ? 1,
      speedFactor ? 1,
      supportedFeatures ? [ ],
      mandatoryFeatures ? [ ],
      publicHostKey ? null,
    }:
    compact {
      inherit
        hostName
        systems
        protocol
        sshUser
        sshKey
        maxJobs
        speedFactor
        supportedFeatures
        mandatoryFeatures
        publicHostKey
        ;
    };

  mkDistributedBuildConfig =
    {
      machines,
      useSubstitutes ? true,
    }:
    {
      distributedBuilds = true;
      settings.builders-use-substitutes = useSubstitutes;
      buildMachines = map (machine: machine) machines;
    };

  mkBuildersFragment =
    {
      machines,
      useSubstitutes ? true,
    }:
    let
      renderMachine =
        machine:
        let
          normalized = compact machine;
          sshTarget =
            if normalized ? sshUser then
              "${normalized.sshUser}@${normalized.hostName}"
            else
              normalized.hostName;
          featureString = concatStringsSep "," normalized.supportedFeatures;
          mandatoryString = concatStringsSep "," normalized.mandatoryFeatures;
        in
        concatStringsSep " " (
          [
            sshTarget
            (concatStringsSep "," normalized.systems)
            (if normalized ? sshKey then toString normalized.sshKey else "-")
            (toString normalized.maxJobs)
            (toString normalized.speedFactor)
            featureString
            mandatoryString
          ]
          ++ optionals (normalized ? publicHostKey) [ normalized.publicHostKey ]
        );
    in
    {
      builders = concatStringsSep ";" (map renderMachine machines);
      builders-use-substitutes = useSubstitutes;
    };
}
