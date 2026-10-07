ARG GAME_IMAGE
FROM node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e AS node
FROM ${GAME_IMAGE}
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY server.mjs episode-files.mts game-hosted.mts game-outcome.mts game-process.mts protocol.mts /opt/worlds/
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["node", "/opt/worlds/server.mjs"]
