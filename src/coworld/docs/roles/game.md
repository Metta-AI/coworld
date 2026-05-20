# Game Role

The game owns an episode. It receives an episode config, accepts one or more player connections, advances the world, and
emits the replay and results artifacts.

Runtime contract:

- read `COGAME_CONFIG_URI`;
- serve `GET /healthz`;
- expose the game-defined player and global protocols;
- write a replay file and results file when the episode completes.

