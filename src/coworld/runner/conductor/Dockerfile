ARG GAME_IMAGE
FROM node:24.14.1-bookworm-slim@sha256:b506e7321f176aae77317f99d67a24b272c1f09f1d10f1761f2773447d8da26c AS node
FROM ${GAME_IMAGE}
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY server.mjs episode-files.mts game-hosted.mts game-outcome.mts game-process.mts protocol.mts /opt/worlds/
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["node", "/opt/worlds/server.mjs"]
