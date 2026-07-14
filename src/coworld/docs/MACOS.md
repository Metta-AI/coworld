# Coworld on macOS

Current Coworld game and player images are `linux/amd64`. On Apple Silicon, use either OrbStack or Colima with Rosetta,
then set Docker's default platform before running Coworld locally.

Choose one Docker provider:

### OrbStack

Install [OrbStack](https://orbstack.dev/), then run:

```bash
orb start
orb config set rosetta true
```

### Colima

Install [Colima](https://github.com/abiosoft/colima) and the Docker client, then run:

```bash
brew install colima docker
colima start --vm-type=vz --vz-rosetta
```

With either provider, run:

```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64
docker info
```

Add the `export` line to `~/.zshrc` to keep it across new terminals.
