# Player Role

Players connect to the game for one episode and implement the game-defined player protocol. A bundled player is useful
for certification, examples, baselines, or starter policies.

Runtime contract:

- receive `COGAMES_ENGINE_WS_URL`;
- speak the game-owned player protocol;
- act only for the player slot assigned by the episode runner.

