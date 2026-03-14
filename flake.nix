{
  description = "Remote Nix build helper with explicit upload progress";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      builderLib = import ./nix/lib.nix { lib = nixpkgs.lib; };
    in
    {
      lib = builderLib;

      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.python311Packages.buildPythonPackage {
            pname = "builder";
            version = "0.1.0";
            src = ./.;
            pyproject = true;

            build-system = with pkgs.python311Packages; [
              hatchling
            ];

            # Runtime dependencies (nix, ssh are external)
            dependencies = [ ];

            # Check phase
            nativeCheckInputs = with pkgs.python311Packages; [
              pytestCheckHook
            ];

            # These tools are expected to be in PATH at runtime
            # Users should ensure nix and openssh are available
            postInstall = ''
              wrapProgram $out/bin/builder \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.nix pkgs.openssh ]}
            '';

            meta = with pkgs.lib; {
              description = "Remote Nix build helper with explicit upload progress";
              homepage = "https://github.com/codegod100/builder";
              license = licenses.mit;
              mainProgram = "builder";
              platforms = platforms.unix;
            };
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              python311
              python311Packages.pytest
              nix
              openssh
            ];
          };
        });

      # For use as an overlay
      overlays.default = final: prev: {
        builder = self.packages.${final.system}.default;
      };

      nixosModules.default = import ./nix/modules/remote-builders.nix;
      darwinModules.default = self.nixosModules.default;
    };
}
