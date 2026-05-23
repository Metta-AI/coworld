import pixie, protocol, ../../sim, ../../texts, ../../votereader,
  ../../../common/server
when not defined(italkalotLibrary):
  import whisky
  when not defined(botHeadless):
    import silky, windy
import std/[algorithm, heapqueue, monotimes, options, os, parseopt, random,
  strutils, times]

const
  PlayerScreenX = ScreenWidth div 2
  PlayerScreenY = ScreenHeight div 2
  PlayerWorldOffX = SpriteDrawOffX + PlayerScreenX - SpriteSize div 2
  PlayerWorldOffY = SpriteDrawOffY + PlayerScreenY - SpriteSize div 2
  FullFrameFitMaxErrors = 420
  LocalFrameFitMaxErrors = 320
  FrameFitMinCompared = 12000
  LocalFrameSearchRadius = 8
  PatchSize = 8
  PatchGridW = ScreenWidth div PatchSize
  PatchGridH = ScreenHeight div PatchSize
  PatchHashBase = 16777619'u64
  PatchHashSeed = 14695981039346656037'u64
  PatchMaxMatches = 4096
  PatchTopCandidates = 16
  PatchMinVotes = 3
  PlayerIgnoreRadius = 9
  InterstitialBlackPercent = 30
  HomeSearchRadius = 20
  PlayerDefaultPort = DefaultPort
  ViewerWindowWidth = 1820
  ViewerWindowHeight = 1060
  ViewerMargin = 16.0'f
  ViewerFrameScale = 4.0'f
  ViewerMapScale = 1.25'f
  ViewerBackground = rgbx(17, 20, 28, 255)
  ViewerPanel = rgbx(33, 38, 50, 255)
  ViewerPanelAlt = rgbx(25, 30, 41, 255)
  ViewerText = rgbx(226, 231, 240, 255)
  ViewerMutedText = rgbx(146, 155, 172, 255)
  ViewerViewport = rgbx(142, 193, 255, 180)
  ViewerButton = rgbx(255, 196, 88, 255)
  ViewerPlayer = rgbx(120, 255, 170, 255)
  ViewerCrew = rgbx(82, 168, 255, 255)
  ViewerImp = rgbx(255, 84, 96, 255)
  ViewerTask = rgbx(255, 132, 146, 255)
  ViewerTaskGuess = rgbx(255, 220, 92, 255)
  ViewerRadarLine = rgbx(255, 220, 92, 210)
  ViewerPath = rgbx(119, 218, 255, 230)
  ViewerWalk = rgbx(46, 61, 75, 255)
  ViewerWall = rgbx(86, 50, 56, 255)
  ViewerUnknown = rgbx(22, 26, 36, 255)
  RadarTaskColor = 8'u8
  RadarPeripheryMargin = 1
  RadarMatchTolerance = 2
  TaskIconSearchRadius = 2
  TaskIconExpectedSearchRadius = 3
  TaskIconMaxMisses = 4
  TaskIconMaybeMisses = 12
  TaskIconInspectSize = 16
  TaskClearScreenMargin = 8
  TaskIconMissThreshold = 24
  PathLookahead = 18
  TaskInnerMargin = 6
  TaskPreciseApproachRadius = 12
  CoastLookaheadTicks = 8
  CoastArrivalPadding = 1
  SteerDeadband = 2
  BrakeDeadband = 1
  StuckFrameThreshold = 8
  JiggleDuration = 16
  TaskHoldPadding = 8
  CrewmateSearchRadius = 1
  CrewmateMaxMisses = 8
  CrewmateMinStablePixels = 8
  CrewmateMinBodyPixels = 8
  KillIconX = 1
  KillIconY = ScreenHeight - SpriteSize - 1
  KillIconMaxMisses = 5
  GhostIconMaxMisses = 3
  GhostIconFrameThreshold = 2
  KillApproachRadius = 3
  BodySearchRadius = 1
  BodyMaxMisses = 9
  BodyMinStablePixels = 6
  BodyMinTintPixels = 6
  GhostSearchRadius = 1
  GhostMaxMisses = 9
  GhostMinStablePixels = 6
  GhostMinTintPixels = 6
  PlayerColorCount = PlayerColors.len
  PlayerColorNames = [
    "red",
    "orange",
    "yellow",
    "light blue",
    "pink",
    "lime",
    "blue",
    "pale blue",
    "gray",
    "white",
    "dark brown",
    "brown",
    "dark teal",
    "green",
    "dark navy",
    "black"
  ]
  VoteCellW = 16
  VoteCellH = 17
  VoteStartY = 2
  VoteSkipW = 28
  VoteUnknown = -1
  VoteSkip = -2
  VoteBlackMarker = 12'u8
  VoteListenBaseTicks = 100
  VoteListenRandomTicks = 100
  ImposterSusChatPercent = 35
  VoteChatIconX = sim.VoteChatIconX
  VoteChatTextX = sim.VoteChatTextX
  VoteChatChars = VoteChatCharsPerLine
  VoteChatSpeakerSearch = 24
  FrameDropThreshold = 32
  MaxFrameDrain = 128

when not defined(italkalotLibrary):
  type ViewerApp = ref object
    when not defined(botHeadless):
      window: Window
      silky: Silky

type
  TileKnowledge = enum
    TileUnknown
    TileOpen
    TileWall

  CameraLock = enum
    NoLock
    LocalFrameMapLock
    FrameMapLock

  TaskState = enum
    TaskNotDoing
    TaskMaybe
    TaskMandatory
    TaskCompleted

  BotRole = enum
    RoleUnknown
    RoleCrewmate
    RoleImposter

  PathNode = object
    priority: int
    index: int

  PathStep = object
    found: bool
    x: int
    y: int

  CameraScore = object
    score: int
    errors: int
    compared: int

  PatchEntry = object
    hash: uint64
    cameraX: int
    cameraY: int

  PatchCandidate = object
    votes: int
    cameraX: int
    cameraY: int

  RadarDot = object
    x: int
    y: int

  IconMatch = object
    x: int
    y: int

  CrewmateMatch = object
    x: int
    y: int
    colorIndex: int
    flipH: bool

  BodyMatch = object
    x: int
    y: int

  GhostMatch = object
    x: int
    y: int
    flipH: bool

  VoteSlot = object
    colorIndex: int
    alive: bool

  VoteChatSpeaker = object
    colorIndex: int
    y: int

  VoteChatLine = object
    speakerColor: int
    y: int
    text: string

  Bot = object
    sim: SimServer
    playerSprite: Sprite
    bodySprite: Sprite
    ghostSprite: Sprite
    taskSprite: Sprite
    killButtonSprite: Sprite
    ghostIconSprite: Sprite
    rng: Rand
    role: BotRole
    isGhost: bool
    ghostIconFrames: int
    imposterKillReady: bool
    imposterGoalIndex: int
    packed: seq[uint8]
    unpacked: seq[uint8]
    mapTiles: seq[TileKnowledge]
    patchEntries: seq[PatchEntry]
    patchVotes: seq[uint16]
    patchTouched: seq[int]
    patchCandidates: seq[PatchCandidate]
    cameraX: int
    cameraY: int
    lastCameraX: int
    lastCameraY: int
    cameraLock: CameraLock
    cameraScore: int
    localized: bool
    interstitial: bool
    interstitialText: string
    lastGameOverText: string
    gameStarted: bool
    homeSet: bool
    homeX: int
    homeY: int
    haveMotionSample: bool
    previousPlayerWorldX: int
    previousPlayerWorldY: int
    velocityX: int
    velocityY: int
    stuckFrames: int
    jiggleTicks: int
    jiggleSide: int
    desiredMask: uint8
    controllerMask: uint8
    taskHoldTicks: int
    taskHoldIndex: int
    frameTick: int
    centerMicros: int
    spriteScanMicros: int
    localizeLocalMicros: int
    localizePatchMicros: int
    localizeSpiralMicros: int
    astarMicros: int
    queuedFrames: seq[string]
    frameBufferLen: int
    framesDropped: int
    skippedFrames: int
    lastMask: uint8
    lastThought: string
    pendingChat: string
    lastBodySeenX: int
    lastBodySeenY: int
    lastBodyReportX: int
    lastBodyReportY: int
    lastSeenTicks: array[PlayerColorCount, int]
    bodySeenTicks: array[PlayerColorCount, int]
    selfColorIndex: int
    knownImposters: array[PlayerColorCount, bool]
    voting: bool
    votePlayerCount: int
    voteCursor: int
    voteSelfSlot: int
    voteTarget: int
    voteStartTick: int
    voteDelayTicks: int
    voteChatSusColor: int
    voteQueuedSusColor: int
    voteImposterChatDecided: bool
    voteChatText: string
    voteChatLines: seq[VoteChatLine]
    voteSlots: array[MaxPlayers, VoteSlot]
    voteChoices: array[PlayerColorCount, int]
    lastVoteFrame: string
    intent: string
    goalX: int
    goalY: int
    goalIndex: int
    goalName: string
    hasGoal: bool
    hasPathStep: bool
    pathStep: PathStep
    path: seq[PathStep]
    radarDots: seq[RadarDot]
    radarTasks: seq[bool]
    checkoutTasks: seq[bool]
    taskStates: seq[TaskState]
    taskIconMisses: seq[int]
    visibleTaskIcons: seq[IconMatch]
    visibleCrewmates: seq[CrewmateMatch]
    visibleBodies: seq[BodyMatch]
    visibleGhosts: seq[GhostMatch]

proc gameDir(): string =
  ## Returns the Among Them game directory.
  let
    sourceDir = currentSourcePath().parentDir().parentDir().parentDir()
    cwd = getCurrentDir()
    candidates = [sourceDir, cwd, cwd.parentDir(), cwd.parentDir().parentDir()]
  for candidate in candidates:
    if fileExists(candidate / "map.json"):
      return candidate
  sourceDir

proc atlasPath(): string =
  ## Returns the shared Silky atlas path.
  gameDir() / ".." / "client" / "dist" / "atlas.png"

proc unpack4bpp(packed: openArray[uint8], unpacked: var seq[uint8]) =
  ## Expands one packed 4 bit framebuffer into palette indices.
  let targetLen = packed.len * 2
  if unpacked.len != targetLen:
    unpacked.setLen(targetLen)
  for i, byte in packed:
    unpacked[i * 2] = byte and 0x0f
    unpacked[i * 2 + 1] = (byte shr 4) and 0x0f

proc sampleColor(index: uint8): ColorRGBX =
  ## Converts one palette index to a Silky color.
  Palette[index and 0x0f].rgbx

proc mapIndexSafe(x, y: int): int =
  ## Returns the map pixel index.
  y * MapWidth + x

proc minCameraX(): int =
  ## Returns the smallest possible centered camera X.
  -ScreenWidth div 2 - SpriteSize

proc maxCameraX(): int =
  ## Returns the largest possible centered camera X.
  MapWidth - ScreenWidth div 2 + SpriteSize

proc minCameraY(): int =
  ## Returns the smallest possible centered camera Y.
  -ScreenHeight div 2 - SpriteSize

proc maxCameraY(): int =
  ## Returns the largest possible centered camera Y.
  MapHeight - ScreenHeight div 2 + SpriteSize

proc cameraIndex(x, y: int): int =
  ## Returns the patch vote index for one camera.
  (y - minCameraY()) * (maxCameraX() - minCameraX() + 1) +
    (x - minCameraX())

proc cameraIndexX(index: int): int =
  ## Returns the camera X coordinate for one vote index.
  minCameraX() + index mod (maxCameraX() - minCameraX() + 1)

proc cameraIndexY(index: int): int =
  ## Returns the camera Y coordinate for one vote index.
  minCameraY() + index div (maxCameraX() - minCameraX() + 1)

proc buttonCameraX(sim: SimServer): int =
  ## Returns the initial camera X guess around the emergency button.
  let button = sim.gameMap.button
  clamp(
    button.x + button.w div 2 - PlayerWorldOffX,
    minCameraX(),
    maxCameraX()
  )

proc buttonCameraY(sim: SimServer): int =
  ## Returns the initial camera Y guess around the emergency button.
  let button = sim.gameMap.button
  clamp(
    button.y + button.h div 2 - PlayerWorldOffY,
    minCameraY(),
    maxCameraY()
  )

proc cameraXForWorld(x: int): int =
  ## Returns the camera X that centers one world X on the player.
  clamp(x - PlayerWorldOffX, minCameraX(), maxCameraX())

proc cameraYForWorld(y: int): int =
  ## Returns the camera Y that centers one world Y on the player.
  clamp(y - PlayerWorldOffY, minCameraY(), maxCameraY())

proc inMap(x, y: int): bool =
  ## Returns true when a world pixel is inside the Skeld map.
  x >= 0 and y >= 0 and x < MapWidth and y < MapHeight

proc cameraCanHoldPlayer(cameraX, cameraY: int): bool =
  ## Returns true when a camera candidate can center a real player.
  inMap(cameraX + PlayerWorldOffX, cameraY + PlayerWorldOffY)

proc playerWorldX(bot: Bot): int =
  ## Returns the inferred player collision X coordinate.
  bot.cameraX + PlayerWorldOffX

proc playerWorldY(bot: Bot): int =
  ## Returns the inferred player collision Y coordinate.
  bot.cameraY + PlayerWorldOffY

proc roomName(bot: Bot): string =
  ## Returns the room containing the inferred player position.
  if not bot.localized:
    return "unknown"
  let
    px = bot.playerWorldX() + CollisionW div 2
    py = bot.playerWorldY() + CollisionH div 2
  for room in bot.sim.rooms:
    if px >= room.x and px < room.x + room.w and
        py >= room.y and py < room.y + room.h:
      return room.name
  "unknown"

proc roomNameAt(bot: Bot, x, y: int): string =
  ## Returns the room containing one world point.
  for room in bot.sim.rooms:
    if x >= room.x and x < room.x + room.w and
        y >= room.y and y < room.y + room.h:
      return room.name
  "unknown"

proc taskCenter(task: TaskStation): tuple[x: int, y: int] =
  ## Returns the center pixel for a task station.
  (task.x + task.w div 2, task.y + task.h div 2)

proc `<`(a, b: PathNode): bool =
  ## Orders path nodes for Nim heapqueue.
  if a.priority == b.priority:
    return a.index < b.index
  a.priority < b.priority

proc `<`(a, b: PatchEntry): bool =
  ## Orders patch entries by hash and scan order.
  if a.hash == b.hash:
    if a.cameraY == b.cameraY:
      a.cameraX < b.cameraX
    else:
      a.cameraY < b.cameraY
  else:
    a.hash < b.hash

proc cmpPatchCandidate(a, b: PatchCandidate): int =
  ## Sorts patch candidates by votes and scan order.
  if a.votes != b.votes:
    return cmp(b.votes, a.votes)
  if a.cameraY != b.cameraY:
    return cmp(a.cameraY, b.cameraY)
  cmp(a.cameraX, b.cameraX)

proc tileWidth(): int =
  ## Returns the path grid width in pixels.
  MapWidth

proc ignoreTaskIconPixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to a matched task icon.
  for icon in bot.visibleTaskIcons:
    let
      ix = sx - icon.x
      iy = sy - icon.y
    if ix < 0 or iy < 0 or
        ix >= bot.taskSprite.width or
        iy >= bot.taskSprite.height:
      continue
    if bot.taskSprite.pixels[bot.taskSprite.spriteIndex(ix, iy)] !=
        TransparentColorIndex:
      return true

proc ignoreCrewmatePixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to a matched crewmate.
  for crewmate in bot.visibleCrewmates:
    let
      ix = sx - crewmate.x
      iy = sy - crewmate.y
    if ix < 0 or iy < 0 or
        ix >= bot.playerSprite.width or
        iy >= bot.playerSprite.height:
      continue
    let srcX =
      if crewmate.flipH:
        bot.playerSprite.width - 1 - ix
      else:
        ix
    if bot.playerSprite.pixels[bot.playerSprite.spriteIndex(srcX, iy)] !=
        TransparentColorIndex:
      return true

proc ignoreBodyPixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to a matched dead body.
  for body in bot.visibleBodies:
    let
      ix = sx - body.x
      iy = sy - body.y
    if ix < 0 or iy < 0 or
        ix >= bot.bodySprite.width or
        iy >= bot.bodySprite.height:
      continue
    if bot.bodySprite.pixels[bot.bodySprite.spriteIndex(ix, iy)] !=
        TransparentColorIndex:
      return true

proc ignoreGhostPixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to a matched ghost.
  for ghost in bot.visibleGhosts:
    let
      ix = sx - ghost.x
      iy = sy - ghost.y
    if ix < 0 or iy < 0 or
        ix >= bot.ghostSprite.width or
        iy >= bot.ghostSprite.height:
      continue
    let srcX =
      if ghost.flipH:
        bot.ghostSprite.width - 1 - ix
      else:
        ix
    if bot.ghostSprite.pixels[bot.ghostSprite.spriteIndex(srcX, iy)] !=
        TransparentColorIndex:
      return true

proc ignoreKillIconPixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to the imposter kill icon.
  if bot.role != RoleImposter:
    return false
  let
    ix = sx - KillIconX
    iy = sy - KillIconY
  if ix < 0 or iy < 0 or
      ix >= bot.killButtonSprite.width or
      iy >= bot.killButtonSprite.height:
    return false
  bot.killButtonSprite.pixels[
    bot.killButtonSprite.spriteIndex(ix, iy)
  ] != TransparentColorIndex

proc ignoreGhostIconPixel(bot: Bot, sx, sy: int): bool =
  ## Returns true when a frame pixel belongs to the fixed ghost icon.
  if not bot.isGhost and bot.ghostIconFrames == 0:
    return false
  let
    ix = sx - KillIconX
    iy = sy - KillIconY
  if ix < 0 or iy < 0 or
      ix >= bot.ghostIconSprite.width or
      iy >= bot.ghostIconSprite.height:
    return false
  bot.ghostIconSprite.pixels[
    bot.ghostIconSprite.spriteIndex(ix, iy)
  ] != TransparentColorIndex

proc ignoreFramePixel(bot: Bot, frameColor: uint8, sx, sy: int): bool =
  ## Returns true for dynamic screen pixels that are not map evidence.
  if frameColor == RadarTaskColor:
    return true
  if bot.ignoreKillIconPixel(sx, sy):
    return true
  if bot.ignoreGhostIconPixel(sx, sy):
    return true
  if bot.ignoreBodyPixel(sx, sy):
    return true
  if bot.ignoreGhostPixel(sx, sy):
    return true
  if bot.ignoreTaskIconPixel(sx, sy):
    return true
  if bot.ignoreCrewmatePixel(sx, sy):
    return true
  abs(sx - PlayerScreenX) <= PlayerIgnoreRadius and
    abs(sy - PlayerScreenY) <= PlayerIgnoreRadius

proc scoreCamera(bot: Bot, cameraX, cameraY, maxErrors: int): CameraScore =
  ## Counts map-fit errors for a full 128x128 frame rectangle.
  for sy in 0 ..< ScreenHeight:
    for sx in 0 ..< ScreenWidth:
      let frameColor = bot.unpacked[sy * ScreenWidth + sx]
      if bot.ignoreFramePixel(frameColor, sx, sy):
        continue
      let
        mx = cameraX + sx
        my = cameraY + sy
        mapColor =
          if inMap(mx, my):
            bot.sim.mapPixels[mapIndexSafe(mx, my)]
          else:
            MapVoidColor
      if frameColor == mapColor:
        inc result.compared
      elif ShadowMap[mapColor and 0x0f] == frameColor:
        inc result.compared
      else:
        inc result.compared
        inc result.errors
        if result.errors > maxErrors:
          result.score = -result.errors
          return
  result.score = result.compared - result.errors * ScreenWidth

proc patchHashAdd(hash: uint64, color: uint8): uint64 =
  ## Adds one color to an 8 by 8 patch hash.
  hash * PatchHashBase + uint64(color and 0x0f) + 1'u64

proc patchMapColor(bot: Bot, x, y: int): uint8 =
  ## Returns the map color used by patch localization.
  if inMap(x, y):
    bot.sim.mapPixels[mapIndexSafe(x, y)]
  else:
    MapVoidColor

proc mapPatchHash(bot: Bot, x, y: int): uint64 =
  ## Hashes one 8 by 8 map patch.
  result = PatchHashSeed
  for py in 0 ..< PatchSize:
    for px in 0 ..< PatchSize:
      result = patchHashAdd(result, bot.patchMapColor(x + px, y + py))

proc framePatchHash(
  bot: Bot,
  sx,
  sy: int,
  hash: var uint64
): bool =
  ## Hashes one clean 8 by 8 frame patch.
  hash = PatchHashSeed
  for py in 0 ..< PatchSize:
    for px in 0 ..< PatchSize:
      let
        x = sx + px
        y = sy + py
        color = bot.unpacked[y * ScreenWidth + x]
      if bot.ignoreFramePixel(color, x, y):
        return false
      hash = patchHashAdd(hash, color)
  true

proc buildPatchEntries(bot: var Bot) =
  ## Builds a map patch hash index for fast localization.
  let
    minX = minCameraX()
    maxX = maxCameraX() + ScreenWidth - PatchSize
    minY = minCameraY()
    maxY = maxCameraY() + ScreenHeight - PatchSize
    width = maxCameraX() - minCameraX() + 1
    height = maxCameraY() - minCameraY() + 1
  bot.patchEntries = @[]
  bot.patchEntries.setLen((maxX - minX + 1) * (maxY - minY + 1))
  var i = 0
  for y in minY .. maxY:
    for x in minX .. maxX:
      bot.patchEntries[i] = PatchEntry(
        hash: bot.mapPatchHash(x, y),
        cameraX: x,
        cameraY: y
      )
      inc i
  bot.patchEntries.sort()
  bot.patchVotes = newSeq[uint16](width * height)
  bot.patchTouched = @[]
  bot.patchCandidates = @[]

proc patchHashRange(
  entries: openArray[PatchEntry],
  hash: uint64
): tuple[first, last: int] =
  ## Returns the sorted range with a matching patch hash.
  var
    lo = 0
    hi = entries.len
  while lo < hi:
    let mid = (lo + hi) div 2
    if entries[mid].hash < hash:
      lo = mid + 1
    else:
      hi = mid
  result.first = lo
  hi = entries.len
  while lo < hi:
    let mid = (lo + hi) div 2
    if entries[mid].hash > hash:
      hi = mid
    else:
      lo = mid + 1
  result.last = lo

proc addPatchVote(bot: var Bot, x, y: int) =
  ## Adds one patch vote for a camera candidate.
  if x < minCameraX() or x > maxCameraX() or
      y < minCameraY() or y > maxCameraY():
    return
  if not cameraCanHoldPlayer(x, y):
    return
  let index = cameraIndex(x, y)
  if bot.patchVotes[index] == 0:
    bot.patchTouched.add(index)
  bot.patchVotes[index] = bot.patchVotes[index] + 1

proc collectPatchCandidates(bot: var Bot) =
  ## Collects the best voted camera candidates.
  bot.patchCandidates.setLen(0)
  for index in bot.patchTouched:
    let votes = bot.patchVotes[index].int
    if votes < PatchMinVotes:
      continue
    bot.patchCandidates.add(PatchCandidate(
      votes: votes,
      cameraX: cameraIndexX(index),
      cameraY: cameraIndexY(index)
    ))
  bot.patchCandidates.sort(cmpPatchCandidate)
  if bot.patchCandidates.len > PatchTopCandidates:
    bot.patchCandidates.setLen(PatchTopCandidates)

proc clearPatchVotes(bot: var Bot) =
  ## Clears patch vote counters touched by the last localization pass.
  for index in bot.patchTouched:
    bot.patchVotes[index] = 0
  bot.patchTouched.setLen(0)

proc acceptCameraScore(score: CameraScore, maxErrors: int): bool

proc setCameraLock(
  bot: var Bot,
  x,
  y: int,
  score: CameraScore,
  lock: CameraLock
)

proc locateByPatches(bot: var Bot): bool =
  ## Locates the camera using 8 by 8 map patch votes.
  if bot.patchEntries.len == 0:
    return false
  bot.clearPatchVotes()
  for py in 0 ..< PatchGridH:
    for px in 0 ..< PatchGridW:
      let
        sx = px * PatchSize
        sy = py * PatchSize
      var hash = 0'u64
      if not bot.framePatchHash(sx, sy, hash):
        continue
      let range = patchHashRange(bot.patchEntries, hash)
      if range.last - range.first > PatchMaxMatches:
        continue
      for i in range.first ..< range.last:
        let
          entry = bot.patchEntries[i]
          x = entry.cameraX - sx
          y = entry.cameraY - sy
        bot.addPatchVote(x, y)
  bot.collectPatchCandidates()
  var
    bestScore = CameraScore(score: low(int), errors: high(int), compared: 0)
    bestX = 0
    bestY = 0
  for candidate in bot.patchCandidates:
    let score = bot.scoreCamera(
      candidate.cameraX,
      candidate.cameraY,
      FullFrameFitMaxErrors
    )
    if score.errors < bestScore.errors or
        (score.errors == bestScore.errors and
        score.compared > bestScore.compared):
      bestScore = score
      bestX = candidate.cameraX
      bestY = candidate.cameraY
  bot.clearPatchVotes()
  if not acceptCameraScore(bestScore, FullFrameFitMaxErrors):
    return false
  bot.setCameraLock(bestX, bestY, bestScore, FrameMapLock)
  true

proc acceptCameraScore(score: CameraScore, maxErrors: int): bool =
  ## Returns true when a camera score is good enough to trust.
  score.errors <= maxErrors and score.compared >= FrameFitMinCompared

proc setCameraLock(
  bot: var Bot,
  x,
  y: int,
  score: CameraScore,
  lock: CameraLock
) =
  ## Stores one accepted camera lock.
  bot.cameraX = x
  bot.cameraY = y
  bot.cameraScore = score.score
  bot.cameraLock = lock
  bot.localized = true

proc scanTaskIcons(bot: var Bot)

proc scanCrewmates(bot: var Bot)

proc rememberRoleReveal(bot: var Bot)

proc scanBodies(bot: var Bot)

proc scanGhosts(bot: var Bot)

proc updateRole(bot: var Bot)

proc updateSelfColor(bot: var Bot)

proc parseVotingScreen(bot: var Bot): bool

proc asciiTextWidth(bot: Bot, text: string): int =
  ## Returns the tiny UI text width.
  texts.asciiTextWidth(bot.sim.asciiSprites, text)

proc asciiTextMatches(bot: Bot, text: string, x, y: int): bool =
  ## Returns true when text is visible at the given screen position.
  texts.asciiTextMatches(bot.unpacked, bot.sim.asciiSprites, text, x, y)

proc findAsciiText(bot: Bot, text: string): bool =
  ## Finds a rendered ASCII phrase in the top black-screen title area.
  let maxX = ScreenWidth - bot.asciiTextWidth(text)
  if maxX < 0:
    return false
  for y in 0 .. 20:
    for x in 0 .. maxX:
      if bot.asciiTextMatches(text, x, y):
        return true

proc readAsciiLine(bot: Bot, y: int): string =
  ## Reads a loose ASCII line from one black-screen text row.
  texts.readAsciiLine(bot.unpacked, bot.sim.asciiSprites, y)

proc detectInterstitialText(bot: Bot): string =
  ## Reads known interstitial ASCII text from a black screen.
  if bot.findAsciiText("CREW WINS"):
    return "CREW WINS"
  if bot.findAsciiText("IMPS WIN"):
    return "IMPS WIN"
  if bot.findAsciiText("IMPS"):
    return "IMPS"
  if bot.findAsciiText("CREWMATE"):
    return "CREWMATE"
  for y in 0 .. 20:
    let line = bot.readAsciiLine(y)
    if line.len > 0 and line != "??????????????????":
      return line
  ""

proc isGameOverText(text: string): bool =
  ## Returns true when interstitial text means the round has ended.
  text == "CREW WINS" or text == "IMPS WIN"

proc clearVotingState(bot: var Bot) =
  ## Clears the parsed voting screen state.
  bot.voting = false
  bot.votePlayerCount = 0
  bot.voteCursor = VoteUnknown
  bot.voteSelfSlot = VoteUnknown
  bot.voteTarget = VoteUnknown
  bot.voteStartTick = -1
  bot.voteDelayTicks = -1
  bot.voteChatSusColor = VoteUnknown
  bot.voteQueuedSusColor = VoteUnknown
  bot.voteImposterChatDecided = false
  bot.voteChatText = ""
  bot.voteChatLines.setLen(0)
  for i in 0 ..< bot.voteSlots.len:
    bot.voteSlots[i].colorIndex = VoteUnknown
    bot.voteSlots[i].alive = false
  for i in 0 ..< bot.voteChoices.len:
    bot.voteChoices[i] = VoteUnknown

proc resetRoundState(bot: var Bot) =
  ## Clears per-round bot state after a detected game-over screen.
  bot.localized = false
  bot.gameStarted = false
  bot.homeSet = false
  bot.homeX = 0
  bot.homeY = 0
  bot.role = RoleCrewmate
  bot.isGhost = false
  bot.ghostIconFrames = 0
  bot.imposterKillReady = false
  bot.imposterGoalIndex = -1
  bot.cameraLock = NoLock
  bot.cameraScore = 0
  bot.haveMotionSample = false
  bot.velocityX = 0
  bot.velocityY = 0
  bot.stuckFrames = 0
  bot.jiggleTicks = 0
  bot.jiggleSide = 0
  bot.desiredMask = 0
  bot.controllerMask = 0
  bot.taskHoldTicks = 0
  bot.taskHoldIndex = -1
  bot.pendingChat = ""
  bot.lastBodySeenX = low(int)
  bot.lastBodySeenY = low(int)
  bot.lastBodyReportX = low(int)
  bot.lastBodyReportY = low(int)
  bot.selfColorIndex = -1
  bot.lastVoteFrame = ""
  bot.clearVotingState()
  for i in 0 ..< bot.lastSeenTicks.len:
    bot.lastSeenTicks[i] = 0
  for i in 0 ..< bot.bodySeenTicks.len:
    bot.bodySeenTicks[i] = 0
  for i in 0 ..< bot.knownImposters.len:
    bot.knownImposters[i] = false
  bot.goalIndex = -1
  bot.goalName = ""
  bot.hasGoal = false
  bot.hasPathStep = false
  bot.path.setLen(0)
  bot.radarDots.setLen(0)
  bot.visibleTaskIcons.setLen(0)
  bot.visibleCrewmates.setLen(0)
  bot.visibleBodies.setLen(0)
  bot.visibleGhosts.setLen(0)
  if bot.radarTasks.len != bot.sim.tasks.len:
    bot.radarTasks = newSeq[bool](bot.sim.tasks.len)
  else:
    for i in 0 ..< bot.radarTasks.len:
      bot.radarTasks[i] = false
  if bot.checkoutTasks.len != bot.sim.tasks.len:
    bot.checkoutTasks = newSeq[bool](bot.sim.tasks.len)
  else:
    for i in 0 ..< bot.checkoutTasks.len:
      bot.checkoutTasks[i] = false
  if bot.taskStates.len != bot.sim.tasks.len:
    bot.taskStates = newSeq[TaskState](bot.sim.tasks.len)
  else:
    for i in 0 ..< bot.taskStates.len:
      bot.taskStates[i] = TaskNotDoing
  if bot.taskIconMisses.len != bot.sim.tasks.len:
    bot.taskIconMisses = newSeq[int](bot.sim.tasks.len)
  else:
    for i in 0 ..< bot.taskIconMisses.len:
      bot.taskIconMisses[i] = 0

proc reseedLocalizationAtHome(bot: var Bot) =
  ## Re-seeds localization around the remembered home point.
  if bot.homeSet:
    bot.cameraX = cameraXForWorld(bot.homeX)
    bot.cameraY = cameraYForWorld(bot.homeY)
  else:
    bot.cameraX = bot.sim.buttonCameraX()
    bot.cameraY = bot.sim.buttonCameraY()
  bot.lastCameraX = bot.cameraX
  bot.lastCameraY = bot.cameraY
  bot.cameraLock = NoLock
  bot.cameraScore = 0
  bot.localized = false
  bot.haveMotionSample = false
  bot.velocityX = 0
  bot.velocityY = 0
  bot.stuckFrames = 0
  bot.jiggleTicks = 0
  bot.jiggleSide = 0
  bot.desiredMask = 0
  bot.controllerMask = 0
  bot.taskHoldTicks = 0
  bot.taskHoldIndex = -1
  bot.goalIndex = -1
  bot.goalName = ""
  bot.hasGoal = false
  bot.hasPathStep = false
  bot.path.setLen(0)

proc isInterstitialScreen(bot: Bot): bool =
  ## Returns true when a black modal screen hides the map.
  var black = 0
  for color in bot.unpacked:
    if color == SpaceColor:
      inc black
  black * 100 >= bot.unpacked.len * InterstitialBlackPercent

proc locateNearFrame(bot: var Bot): bool =
  ## Tracks camera by scanning near the previous accepted camera.
  if not bot.localized:
    return false
  var
    bestScore = CameraScore(score: low(int), errors: high(int), compared: 0)
    bestX = bot.cameraX
    bestY = bot.cameraY
  let
    minX = max(minCameraX(), bot.cameraX - LocalFrameSearchRadius)
    maxX = min(maxCameraX(), bot.cameraX + LocalFrameSearchRadius)
    minY = max(minCameraY(), bot.cameraY - LocalFrameSearchRadius)
    maxY = min(maxCameraY(), bot.cameraY + LocalFrameSearchRadius)
  for y in minY .. maxY:
    for x in minX .. maxX:
      let score = bot.scoreCamera(x, y, LocalFrameFitMaxErrors)
      if score.errors < bestScore.errors or
          (score.errors == bestScore.errors and
          score.compared > bestScore.compared):
        bestScore = score
        bestX = x
        bestY = y
        if bestScore.errors == 0 and
            bestScore.compared >= FrameFitMinCompared:
          break
    if bestScore.errors == 0 and bestScore.compared >= FrameFitMinCompared:
      break
  if not acceptCameraScore(bestScore, LocalFrameFitMaxErrors):
    return false
  bot.setCameraLock(bestX, bestY, bestScore, LocalFrameMapLock)
  true

proc locateByFrame(bot: var Bot): bool =
  ## Locates the camera by spiraling out from the best prior.
  let patchStart = getMonoTime()
  if bot.locateByPatches():
    bot.localizePatchMicros = int((getMonoTime() - patchStart).inMicroseconds)
    bot.localizeSpiralMicros = 0
    return true
  bot.localizePatchMicros = int((getMonoTime() - patchStart).inMicroseconds)
  let spiralStart = getMonoTime()
  var
    bestScore = CameraScore(
      score: low(int),
      errors: high(int),
      compared: 0
    )
    bestX =
      if bot.gameStarted:
        bot.cameraX
      else:
        bot.sim.buttonCameraX()
    bestY =
      if bot.gameStarted:
        bot.cameraY
      else:
        bot.sim.buttonCameraY()
  let
    minX = minCameraX()
    maxX = maxCameraX()
    minY = minCameraY()
    maxY = maxCameraY()
    seedX = clamp(bestX, minX, maxX)
    seedY = clamp(bestY, minY, maxY)
    maxRadius = max(
      max(abs(seedX - minX), abs(seedX - maxX)),
      max(abs(seedY - minY), abs(seedY - maxY))
    )
  bestX = seedX
  bestY = seedY

  template tryCamera(x, y: int): bool =
    ## Scores one camera candidate if the player could be there.
    if x < minX or x > maxX or y < minY or y > maxY:
      false
    elif not cameraCanHoldPlayer(x, y):
      false
    else:
      let score = bot.scoreCamera(x, y, FullFrameFitMaxErrors)
      if score.errors < bestScore.errors or
          (score.errors == bestScore.errors and
          score.compared > bestScore.compared):
        bestScore = score
        bestX = x
        bestY = y
        bestScore.errors == 0 and
          bestScore.compared >= FrameFitMinCompared
      else:
        false

  var done = tryCamera(seedX, seedY)
  for radius in 1 .. maxRadius:
    if done:
      break
    for dx in -radius .. radius:
      if tryCamera(seedX + dx, seedY - radius):
        done = true
        break
      if tryCamera(seedX + dx, seedY + radius):
        done = true
        break
    if done:
      break
    for dy in -radius + 1 .. radius - 1:
      if tryCamera(seedX - radius, seedY + dy):
        done = true
        break
      if tryCamera(seedX + radius, seedY + dy):
        done = true
        break
  if not acceptCameraScore(bestScore, FullFrameFitMaxErrors):
    bot.cameraLock = NoLock
    bot.cameraScore = bestScore.score
    bot.localized = false
    bot.localizeSpiralMicros =
      int((getMonoTime() - spiralStart).inMicroseconds)
    return false
  bot.setCameraLock(bestX, bestY, bestScore, FrameMapLock)
  bot.localizeSpiralMicros =
    int((getMonoTime() - spiralStart).inMicroseconds)
  true

proc updateLocation(bot: var Bot) =
  ## Updates the camera and player world estimate from the frame.
  let wasInterstitial = bot.interstitial
  bot.spriteScanMicros = 0
  bot.localizeLocalMicros = 0
  bot.localizePatchMicros = 0
  bot.localizeSpiralMicros = 0
  bot.lastCameraX = bot.cameraX
  bot.lastCameraY = bot.cameraY
  bot.interstitial = bot.isInterstitialScreen()
  if bot.interstitial:
    bot.interstitialText = bot.detectInterstitialText()
    bot.visibleTaskIcons.setLen(0)
    bot.visibleCrewmates.setLen(0)
    bot.visibleBodies.setLen(0)
    bot.visibleGhosts.setLen(0)
    if bot.interstitialText.isGameOverText() and
        bot.lastGameOverText != bot.interstitialText:
      bot.resetRoundState()
      bot.lastGameOverText = bot.interstitialText
    elif not bot.parseVotingScreen():
      bot.rememberRoleReveal()
    return
  bot.interstitialText = ""
  bot.lastGameOverText = ""
  if bot.voting:
    bot.lastVoteFrame = ""
    bot.clearVotingState()
  if wasInterstitial:
    bot.reseedLocalizationAtHome()
  let spriteStart = getMonoTime()
  bot.updateRole()
  bot.updateSelfColor()
  bot.scanBodies()
  bot.scanGhosts()
  bot.scanCrewmates()
  if bot.role == RoleImposter and not bot.isGhost:
    bot.visibleTaskIcons.setLen(0)
  else:
    bot.scanTaskIcons()
  bot.spriteScanMicros = int((getMonoTime() - spriteStart).inMicroseconds)
  let localStart = getMonoTime()
  if bot.locateNearFrame():
    bot.localizeLocalMicros =
      int((getMonoTime() - localStart).inMicroseconds)
    return
  bot.localizeLocalMicros =
    int((getMonoTime() - localStart).inMicroseconds)
  discard bot.locateByFrame()

proc rememberVisibleMap(bot: var Bot) =
  ## Copies visible walk and wall knowledge into the coarse map model.
  if not bot.localized:
    return
  for sy in 0 ..< ScreenHeight:
    for sx in 0 ..< ScreenWidth:
      let
        mx = bot.cameraX + sx
        my = bot.cameraY + sy
      if not inMap(mx, my):
        continue
      let idx = mapIndexSafe(mx, my)
      if bot.sim.wallMask[idx]:
        bot.mapTiles[idx] = TileWall
      elif bot.sim.walkMask[idx]:
        bot.mapTiles[idx] = TileOpen

proc isRadarPeriphery(x, y: int): bool =
  ## Returns true for pixels in the task radar strip.
  x <= RadarPeripheryMargin or y <= RadarPeripheryMargin or
    x >= ScreenWidth - 1 - RadarPeripheryMargin or
    y >= ScreenHeight - 1 - RadarPeripheryMargin

proc addRadarDot(dots: var seq[RadarDot], x, y: int) =
  ## Adds one radar dot unless a nearby dot is already present.
  for dot in dots:
    if abs(dot.x - x) <= 1 and abs(dot.y - y) <= 1:
      return
  dots.add(RadarDot(x: x, y: y))

proc scanRadarDots(bot: var Bot) =
  ## Scans screen periphery for yellow task radar pixels.
  bot.radarDots.setLen(0)
  for y in 0 ..< ScreenHeight:
    for x in 0 ..< ScreenWidth:
      if not isRadarPeriphery(x, y):
        continue
      if bot.unpacked[y * ScreenWidth + x] == RadarTaskColor:
        bot.radarDots.addRadarDot(x, y)

proc spriteMisses(
  frame: openArray[uint8],
  sprite: Sprite,
  x,
  y: int
): tuple[misses: int, opaque: int] =
  ## Counts opaque sprite pixels that do not match the frame.
  var
    misses = 0
    opaque = 0
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let color = sprite.pixels[sprite.spriteIndex(sx, sy)]
      if color == TransparentColorIndex:
        continue
      inc opaque
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif frame[fy * ScreenWidth + fx] == color:
        discard
      else:
        inc misses
  (misses, opaque)

proc matchesSprite(
  frame: openArray[uint8],
  sprite: Sprite,
  x,
  y: int
): bool =
  ## Returns true if a sprite stringently matches the frame.
  let score = spriteMisses(frame, sprite, x, y)
  score.opaque > 0 and score.misses <= TaskIconMaxMisses

proc maybeMatchesSprite(
  frame: openArray[uint8],
  sprite: Sprite,
  x,
  y: int
): bool =
  ## Returns true when a sprite may be present but imperfect.
  let score = spriteMisses(frame, sprite, x, y)
  score.opaque > 0 and score.misses <= TaskIconMaybeMisses

proc matchesSpriteShadowed(
  frame: openArray[uint8],
  sprite: Sprite,
  x,
  y: int
): bool =
  ## Returns true if a shadowed sprite matches the frame.
  var
    misses = 0
    opaque = 0
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let color = sprite.pixels[sprite.spriteIndex(sx, sy)]
      if color == TransparentColorIndex:
        continue
      inc opaque
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif frame[fy * ScreenWidth + fx] == ShadowMap[color and 0x0f]:
        discard
      else:
        inc misses
      if misses > KillIconMaxMisses:
        return false
  opaque > 0 and misses <= KillIconMaxMisses

proc updateRole(bot: var Bot) =
  ## Updates the known role from fixed status icons.
  let ghostScore = spriteMisses(
    bot.unpacked,
    bot.ghostIconSprite,
    KillIconX,
    KillIconY
  )
  if ghostScore.opaque > 0 and ghostScore.misses <= GhostIconMaxMisses:
    inc bot.ghostIconFrames
    bot.imposterKillReady = false
    if bot.ghostIconFrames >= GhostIconFrameThreshold:
      bot.isGhost = true
      if bot.role == RoleUnknown:
        bot.role = RoleCrewmate
    return
  elif not bot.isGhost:
    bot.ghostIconFrames = 0

  let lit = matchesSprite(
    bot.unpacked,
    bot.killButtonSprite,
    KillIconX,
    KillIconY
  )
  let shaded = matchesSpriteShadowed(
    bot.unpacked,
    bot.killButtonSprite,
    KillIconX,
    KillIconY
  )
  bot.imposterKillReady = lit
  if lit or shaded:
    bot.role = RoleImposter
  elif bot.role == RoleUnknown:
    bot.role = RoleCrewmate

proc addIconMatch(matches: var seq[IconMatch], x, y: int) =
  ## Adds one icon match unless a nearby icon already exists.
  for match in matches:
    if abs(match.x - x) <= 1 and abs(match.y - y) <= 1:
      return
  matches.add(IconMatch(x: x, y: y))

proc stableCrewmateColor(color: uint8): bool =
  ## Returns true for non-body crewmate sprite pixels.
  color != TransparentColorIndex and
    color != TintColor and
    color != ShadeTintColor

proc playerBodyColor(color: uint8): bool =
  ## Returns true when a frame color can be a crewmate body.
  for playerColor in PlayerColors:
    if color == playerColor:
      return true
    if color == ShadowMap[playerColor and 0x0f]:
      return true

proc playerColorIndex(color: uint8): int =
  ## Returns the tracked player color index for a palette color.
  for i, playerColor in PlayerColors:
    if color == playerColor:
      return i
  -1

proc crewmatePixelMatches(spriteColor, frameColor: uint8): bool =
  ## Returns true when one crewmate sprite pixel matches the frame.
  if spriteColor == TintColor or spriteColor == ShadeTintColor:
    return playerBodyColor(frameColor)
  frameColor == spriteColor

proc crewmateColorIndex(bot: Bot, x, y: int, flipH: bool): int =
  ## Returns the most likely visible color for a crewmate match.
  var counts: array[PlayerColorCount, int]
  for sy in 0 ..< bot.playerSprite.height:
    for sx in 0 ..< bot.playerSprite.width:
      let srcX =
        if flipH:
          bot.playerSprite.width - 1 - sx
        else:
          sx
      let color = bot.playerSprite.pixels[
        bot.playerSprite.spriteIndex(srcX, sy)
      ]
      if color != TintColor:
        continue
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        continue
      let index = playerColorIndex(bot.unpacked[fy * ScreenWidth + fx])
      if index >= 0:
        inc counts[index]
  var bestCount = 0
  result = -1
  for i, count in counts:
    if count > bestCount:
      bestCount = count
      result = i

proc matchesCrewmate(
  bot: Bot,
  x,
  y: int,
  flipH: bool
): bool =
  ## Returns true when stable crewmate pixels match the frame.
  var
    bodyMatched = 0
    bodyPixels = 0
    matchedStable = 0
    misses = 0
    stablePixels = 0
  for sy in 0 ..< bot.playerSprite.height:
    for sx in 0 ..< bot.playerSprite.width:
      let srcX =
        if flipH:
          bot.playerSprite.width - 1 - sx
        else:
          sx
      let color = bot.playerSprite.pixels[
        bot.playerSprite.spriteIndex(srcX, sy)
      ]
      if color == TransparentColorIndex:
        continue
      if stableCrewmateColor(color):
        inc stablePixels
      else:
        inc bodyPixels
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif crewmatePixelMatches(color, bot.unpacked[fy * ScreenWidth + fx]):
        if stableCrewmateColor(color):
          inc matchedStable
        else:
          inc bodyMatched
      else:
        inc misses
      if misses > CrewmateMaxMisses:
        return false
  stablePixels >= CrewmateMinStablePixels and
    matchedStable >= CrewmateMinStablePixels and
    bodyPixels >= CrewmateMinBodyPixels and
    bodyMatched >= CrewmateMinBodyPixels

proc addCrewmateMatch(
  matches: var seq[CrewmateMatch],
  x,
  y: int,
  colorIndex: int,
  flipH: bool
) =
  ## Adds one crewmate match unless a nearby match already exists.
  for i in 0 ..< matches.len:
    if abs(matches[i].x - x) <= CrewmateSearchRadius and
        abs(matches[i].y - y) <= CrewmateSearchRadius:
      if matches[i].colorIndex < 0 and colorIndex >= 0:
        matches[i].colorIndex = colorIndex
      return
  matches.add(CrewmateMatch(
    x: x,
    y: y,
    colorIndex: colorIndex,
    flipH: flipH
  ))

proc scanCrewmates(bot: var Bot) =
  ## Scans the current frame for crewmates by stable sprite pixels.
  bot.visibleCrewmates.setLen(0)
  for y in 0 .. ScreenHeight - bot.playerSprite.height:
    for x in 0 .. ScreenWidth - bot.playerSprite.width:
      if abs(x + SpriteSize div 2 - PlayerScreenX) <= PlayerIgnoreRadius and
          abs(y + SpriteSize div 2 - PlayerScreenY) <= PlayerIgnoreRadius:
        continue
      if bot.matchesCrewmate(x, y, false):
        let colorIndex = bot.crewmateColorIndex(x, y, false)
        bot.visibleCrewmates.addCrewmateMatch(x, y, colorIndex, false)
      elif bot.matchesCrewmate(x, y, true):
        let colorIndex = bot.crewmateColorIndex(x, y, true)
        bot.visibleCrewmates.addCrewmateMatch(x, y, colorIndex, true)
  for crewmate in bot.visibleCrewmates:
    if crewmate.colorIndex >= 0 and
        crewmate.colorIndex < bot.lastSeenTicks.len:
      bot.lastSeenTicks[crewmate.colorIndex] = bot.frameTick

proc updateSelfColor(bot: var Bot) =
  ## Learns the local player's color from the centered player sprite.
  let
    x = PlayerScreenX - bot.playerSprite.width div 2
    y = PlayerScreenY - bot.playerSprite.height div 2
  var colorIndex = -1
  if bot.matchesCrewmate(x, y, false):
    colorIndex = bot.crewmateColorIndex(x, y, false)
  elif bot.matchesCrewmate(x, y, true):
    colorIndex = bot.crewmateColorIndex(x, y, true)
  if colorIndex >= 0 and colorIndex < PlayerColorCount:
    bot.selfColorIndex = colorIndex

proc rememberRoleReveal(bot: var Bot) =
  ## Learns team colors from the role reveal interstitial screen.
  if bot.interstitialText == "CREWMATE":
    if bot.role == RoleUnknown:
      bot.role = RoleCrewmate
    return
  if bot.interstitialText != "IMPS":
    return
  bot.role = RoleImposter
  for y in 0 .. ScreenHeight - bot.playerSprite.height:
    for x in 0 .. ScreenWidth - bot.playerSprite.width:
      if bot.matchesCrewmate(x, y, false):
        let colorIndex = bot.crewmateColorIndex(x, y, false)
        bot.visibleCrewmates.addCrewmateMatch(x, y, colorIndex, false)
      elif bot.matchesCrewmate(x, y, true):
        let colorIndex = bot.crewmateColorIndex(x, y, true)
        bot.visibleCrewmates.addCrewmateMatch(x, y, colorIndex, true)
  for crewmate in bot.visibleCrewmates:
    if crewmate.colorIndex >= 0 and
        crewmate.colorIndex < bot.knownImposters.len:
      bot.knownImposters[crewmate.colorIndex] = true

proc matchesActorSprite(
  bot: Bot,
  sprite: Sprite,
  x,
  y: int,
  flipH: bool,
  maxMisses,
  minStablePixels,
  minTintPixels: int
): bool =
  ## Returns true when a tinted actor sprite matches the frame.
  var
    tintMatched = 0
    tintPixels = 0
    stableMatched = 0
    misses = 0
    stablePixels = 0
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let srcX =
        if flipH:
          sprite.width - 1 - sx
        else:
          sx
      let color = sprite.pixels[sprite.spriteIndex(srcX, sy)]
      if color == TransparentColorIndex:
        continue
      if stableCrewmateColor(color):
        inc stablePixels
      else:
        inc tintPixels
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        inc misses
      elif crewmatePixelMatches(color, bot.unpacked[fy * ScreenWidth + fx]):
        if stableCrewmateColor(color):
          inc stableMatched
        else:
          inc tintMatched
      else:
        inc misses
      if misses > maxMisses:
        return false
  stablePixels >= minStablePixels and
    stableMatched >= minStablePixels and
    tintPixels >= minTintPixels and
    tintMatched >= minTintPixels

proc actorColorIndex(
  bot: Bot,
  sprite: Sprite,
  x,
  y: int,
  flipH: bool
): int =
  ## Returns the most likely tint color for an actor sprite.
  var counts: array[PlayerColorCount, int]
  for sy in 0 ..< sprite.height:
    for sx in 0 ..< sprite.width:
      let srcX =
        if flipH:
          sprite.width - 1 - sx
        else:
          sx
      let color = sprite.pixels[sprite.spriteIndex(srcX, sy)]
      if color != TintColor:
        continue
      let
        fx = x + sx
        fy = y + sy
      if fx < 0 or fy < 0 or fx >= ScreenWidth or fy >= ScreenHeight:
        continue
      let index = playerColorIndex(bot.unpacked[fy * ScreenWidth + fx])
      if index >= 0:
        inc counts[index]
  var bestCount = 0
  result = VoteUnknown
  for i, count in counts:
    if count > bestCount:
      bestCount = count
      result = i

proc voteGridLayout(
  count: int
): tuple[cols: int, rows: int, startX: int, skipX: int, skipY: int] =
  ## Returns the fixed voting grid geometry for a player count.
  result.cols = min(count, 8)
  result.rows = (count + result.cols - 1) div result.cols
  let totalW = result.cols * VoteCellW
  result.startX = (ScreenWidth - totalW) div 2
  result.skipX = (ScreenWidth - VoteSkipW) div 2
  result.skipY = VoteStartY + result.rows * VoteCellH + 1

proc voteCellOrigin(
  count,
  index: int
): tuple[x: int, y: int] =
  ## Returns the top-left voting cell origin for a player slot.
  let layout = voteGridLayout(count)
  (
    layout.startX + (index mod layout.cols) * VoteCellW,
    VoteStartY + (index div layout.cols) * VoteCellH
  )

proc voteSkipTextMatches(bot: Bot, skipX, skipY: int): bool =
  ## Returns true when the voting skip label is visible.
  for y in max(0, skipY - 1) .. min(ScreenHeight - 6, skipY + 1):
    let
      minX = max(0, skipX - 2)
      maxX = min(ScreenWidth - bot.asciiTextWidth("SKIP"), skipX + 2)
    for x in minX .. maxX:
      if bot.asciiTextMatches("SKIP", x, y):
        return true

proc parseVoteSlot(
  bot: Bot,
  count,
  index: int
): VoteSlot =
  ## Parses one voting grid slot.
  result.colorIndex = VoteUnknown
  let
    cell = voteCellOrigin(count, index)
    spriteX = cell.x + (VoteCellW - bot.playerSprite.width) div 2
    spriteY = cell.y + 1
  if bot.matchesCrewmate(spriteX, spriteY, false):
    result.colorIndex = bot.crewmateColorIndex(spriteX, spriteY, false)
    result.alive = true
  elif bot.matchesActorSprite(
    bot.bodySprite,
    spriteX,
    spriteY,
    false,
    BodyMaxMisses,
    BodyMinStablePixels,
    BodyMinTintPixels
  ):
    result.colorIndex = bot.actorColorIndex(
      bot.bodySprite,
      spriteX,
      spriteY,
      false
    )
    result.alive = false

proc voteCellSelected(bot: Bot, count, index: int): bool =
  ## Returns true when the local cursor outlines one player cell.
  let cell = voteCellOrigin(count, index)
  var hits = 0
  for bx in 0 ..< VoteCellW:
    if bot.unpacked[(cell.y - 1) * ScreenWidth + cell.x + bx] == 2'u8:
      inc hits
    if bot.unpacked[(cell.y + VoteCellH - 2) * ScreenWidth + cell.x + bx] ==
        2'u8:
      inc hits
  hits >= VoteCellW

proc voteSkipSelected(bot: Bot, skipX, skipY: int): bool =
  ## Returns true when the local cursor outlines the skip option.
  var hits = 0
  for bx in 0 ..< VoteSkipW:
    if bot.unpacked[(skipY - 1) * ScreenWidth + skipX + bx] == 2'u8:
      inc hits
    if bot.unpacked[(skipY + 6) * ScreenWidth + skipX + bx] == 2'u8:
      inc hits
  hits >= VoteSkipW

proc voteSelfMarkerPresent(
  bot: Bot,
  count,
  index: int,
  colorIndex: int
): bool =
  ## Returns true when a voting slot has the local-player marker.
  if colorIndex < 0 or colorIndex >= PlayerColors.len:
    return false
  let
    cell = voteCellOrigin(count, index)
    markerX = cell.x + VoteCellW div 2 - 1
    markerY = cell.y - 2
    a = bot.unpacked[markerY * ScreenWidth + markerX]
    b = bot.unpacked[markerY * ScreenWidth + markerX + 1]
    color = PlayerColors[colorIndex]
  if color == SpaceColor:
    a == 2'u8 and b == VoteBlackMarker
  else:
    a == color and b == color

proc voteDotColorIndex(bot: Bot, x, y: int): int =
  ## Returns the voter color index for one vote dot position.
  if x < 0 or y < 0 or x >= ScreenWidth or y >= ScreenHeight:
    return VoteUnknown
  let color = bot.unpacked[y * ScreenWidth + x]
  if color == 2'u8 and x > 0 and
      bot.unpacked[y * ScreenWidth + x - 1] == VoteBlackMarker:
    return playerColorIndex(SpaceColor)
  if color == SpaceColor:
    return VoteUnknown
  playerColorIndex(color)

proc parseVoteDotsForTarget(
  bot: var Bot,
  target,
  dotX,
  dotY: int
) =
  ## Parses the compact voter dots for one voting target.
  for row in 0 ..< MaxPlayers:
    let colorIndex = bot.voteDotColorIndex(
      dotX + (row mod 8) * 2,
      dotY + (row div 8)
    )
    if colorIndex >= 0 and colorIndex < bot.voteChoices.len:
      bot.voteChoices[colorIndex] = target

proc readAsciiRun(bot: Bot, x, y, count: int): string =
  ## Reads a fixed-width ASCII run from the current screen.
  texts.readAsciiRun(bot.unpacked, bot.sim.asciiSprites, x, y, count)

proc usefulChatLine(line: string): bool =
  ## Returns true when a parsed chat line contains real letters.
  var
    letters = 0
    unknown = 0
  for ch in line:
    if ch in {'a' .. 'z'} or ch in {'A' .. 'Z'}:
      inc letters
    elif ch == '?':
      inc unknown
  letters >= 2 and unknown * 2 <= max(1, line.len)

proc voteChatY(count: int): int =
  ## Returns the top y coordinate of the voting chat panel.
  voteGridLayout(count).skipY + 10

proc voteChatSpeakerAt(bot: Bot, y: int): int =
  ## Reads one voting chat speaker icon color at a y coordinate.
  if y < 0 or y > ScreenHeight - bot.playerSprite.height:
    return VoteUnknown
  if not bot.matchesCrewmate(VoteChatIconX, y, false):
    return VoteUnknown
  bot.crewmateColorIndex(VoteChatIconX, y, false)

proc readVoteChatSpeakers(bot: Bot, count: int): seq[VoteChatSpeaker] =
  ## Reads visible voting chat speaker icons from the pixel frame.
  let chatY = voteChatY(count)
  for y in chatY + 2 .. ScreenHeight - bot.playerSprite.height:
    let colorIndex = bot.voteChatSpeakerAt(y)
    if colorIndex == VoteUnknown:
      continue
    if result.len > 0 and abs(result[^1].y - y) < SpriteSize div 2:
      continue
    result.add VoteChatSpeaker(
      colorIndex: colorIndex,
      y: y
    )

proc voteChatSpeakerForLine(
  speakers: openArray[VoteChatSpeaker],
  y: int
): int =
  ## Returns the nearest visible speaker color for one chat line.
  result = VoteUnknown
  var bestDistance = VoteChatSpeakerSearch + 1
  for speaker in speakers:
    let distance = abs(speaker.y - y)
    if distance < bestDistance:
      bestDistance = distance
      result = speaker.colorIndex
  if bestDistance > VoteChatSpeakerSearch:
    result = VoteUnknown

proc voteChatTextFromLines(lines: openArray[VoteChatLine]): string =
  ## Flattens parsed voting chat lines into one text string.
  for line in lines:
    if result.len > 0:
      result.add(' ')
    result.add(line.text)

proc readVoteChatLines(bot: Bot, count: int): seq[VoteChatLine] =
  ## Reads visible voting chat text and speaker colors from pixels.
  let
    chatY = voteChatY(count)
    speakers = bot.readVoteChatSpeakers(count)
  var previous = ""
  var previousY = low(int)
  for y in chatY + 2 ..< ScreenHeight - 6:
    let line = bot.readAsciiRun(VoteChatTextX, y, VoteChatChars)
    if not line.usefulChatLine():
      continue
    if line == previous and y - previousY <= 2:
      continue
    result.add VoteChatLine(
      speakerColor: voteChatSpeakerForLine(speakers, y),
      y: y,
      text: line
    )
    previous = line
    previousY = y

proc normalizeChatText(text: string): string =
  ## Normalizes chat text for simple word matching.
  var hadSpace = true
  for ch in text:
    var outCh = ch
    if ch in {'A' .. 'Z'}:
      outCh = char(ord(ch) - ord('A') + ord('a'))
    if outCh in {'a' .. 'z'} or outCh in {'0' .. '9'}:
      result.add(outCh)
      hadSpace = false
    elif not hadSpace:
      result.add(' ')
      hadSpace = true
  result = result.strip()

proc spanGap(aStart, aEnd, bStart, bEnd: int): int =
  ## Returns the number of characters between two text spans.
  if aEnd <= bStart:
    bStart - aEnd
  elif bEnd <= aStart:
    aStart - bEnd
  else:
    0

proc chatSusColorIndex(text: string): int =
  ## Returns the player color that visible chat calls sus.
  let
    padded = " " & text.normalizeChatText() & " "
    susNeedle = " sus "
  result = VoteUnknown
  var
    bestSus = -1
    bestGap = high(int)
    bestLen = -1
  for i, name in PlayerColorNames:
    let colorNeedle = " " & name.normalizeChatText() & " "
    var colorPos = padded.find(colorNeedle)
    while colorPos >= 0:
      let
        colorStart = colorPos + 1
        colorEnd = colorPos + colorNeedle.len - 1
        colorLen = colorEnd - colorStart
      var susPos = padded.find(susNeedle)
      while susPos >= 0:
        let
          susStart = susPos + 1
          susEnd = susPos + susNeedle.len - 1
          gap = spanGap(colorStart, colorEnd, susStart, susEnd)
        if gap <= VoteChatChars * 2 and (
            susStart > bestSus or
            (susStart == bestSus and gap < bestGap) or
            (susStart == bestSus and gap == bestGap and
              colorLen > bestLen)):
          bestSus = susStart
          bestGap = gap
          bestLen = colorLen
          result = i
        susPos = padded.find(susNeedle, susPos + 1)
      colorPos = padded.find(colorNeedle, colorPos + 1)

proc voteSlotForColor(bot: Bot, colorIndex: int): int =
  ## Returns the voting slot index for one player color.
  for i in 0 ..< bot.votePlayerCount:
    if bot.voteSlots[i].colorIndex == colorIndex:
      return i
  VoteUnknown

proc voteTargetCanBeSus(bot: Bot, target: int): bool =
  ## Returns true when a voting target is a living non-self player.
  target >= 0 and
    target < bot.votePlayerCount and
    target != bot.voteSelfSlot and
    bot.voteSlots[target].alive

proc voteSusColorAllowed(bot: Bot, colorIndex: int): bool =
  ## Returns true when a color is a valid player to sus and vote.
  let slot = bot.voteSlotForColor(colorIndex)
  bot.voteTargetCanBeSus(slot)

proc randomVoteDelay(bot: var Bot): int =
  ## Returns this meeting's randomized vote delay in ticks.
  VoteListenBaseTicks + bot.rng.rand(VoteListenRandomTicks - 1)

proc ownSusVotingTarget(bot: Bot): int =
  ## Returns this bot's own valid chat sus target, or unknown.
  if bot.selfColorIndex < 0:
    return VoteUnknown
  for line in bot.voteChatLines:
    if line.speakerColor != bot.selfColorIndex:
      continue
    let colorIndex = chatSusColorIndex(line.text)
    if bot.voteSusColorAllowed(colorIndex):
      return bot.voteSlotForColor(colorIndex)
  VoteUnknown

proc parseVotingCandidate(
  bot: var Bot,
  count,
  startTick: int
): bool =
  ## Parses the voting screen for one possible player count.
  let layout = voteGridLayout(count)
  if not bot.voteSkipTextMatches(layout.skipX, layout.skipY):
    return false
  var slots: array[MaxPlayers, VoteSlot]
  for i in 0 ..< count:
    slots[i] = bot.parseVoteSlot(count, i)
    if slots[i].colorIndex == VoteUnknown:
      return false
    if slots[i].colorIndex != i:
      return false

  let
    previousDelay = bot.voteDelayTicks
    previousQueuedSusColor = bot.voteQueuedSusColor
    previousImposterChatDecided = bot.voteImposterChatDecided
  bot.clearVotingState()
  bot.voting = true
  bot.votePlayerCount = count
  bot.voteStartTick = startTick
  bot.voteDelayTicks =
    if previousDelay >= 0:
      previousDelay
    else:
      bot.randomVoteDelay()
  bot.voteQueuedSusColor = previousQueuedSusColor
  bot.voteImposterChatDecided = previousImposterChatDecided
  bot.voteCursor = VoteUnknown
  bot.voteSelfSlot = VoteUnknown
  for i in 0 ..< count:
    bot.voteSlots[i] = slots[i]
    if slots[i].alive and bot.voteCellSelected(count, i):
      bot.voteCursor = i
    if bot.voteSelfMarkerPresent(count, i, slots[i].colorIndex):
      bot.voteSelfSlot = i
      bot.selfColorIndex = slots[i].colorIndex
    let cell = voteCellOrigin(count, i)
    bot.parseVoteDotsForTarget(
      i,
      cell.x + 1,
      cell.y + bot.playerSprite.height + 2
    )
  if bot.voteSkipSelected(layout.skipX, layout.skipY):
    bot.voteCursor = count
  bot.parseVoteDotsForTarget(
    VoteSkip,
    layout.skipX + VoteSkipW + 2,
    layout.skipY
  )
  bot.voteChatLines = bot.readVoteChatLines(count)
  bot.voteChatText = voteChatTextFromLines(bot.voteChatLines)
  let susColor = chatSusColorIndex(bot.voteChatText)
  bot.voteChatSusColor =
    if bot.voteSusColorAllowed(susColor):
      susColor
    else:
      VoteUnknown
  true

proc parseVotingScreen(bot: var Bot): bool =
  ## Parses the voting interstitial if it is currently visible.
  let startTick =
    if bot.voting and bot.voteStartTick >= 0:
      bot.voteStartTick
    else:
      bot.frameTick
  let read = parseVoteFrame(
    bot.unpacked,
    bot.sim.asciiSprites,
    bot.playerSprite,
    bot.bodySprite
  )
  if read.found:
    let
      previousDelay = bot.voteDelayTicks
      previousQueuedSusColor = bot.voteQueuedSusColor
      previousImposterChatDecided = bot.voteImposterChatDecided
    bot.clearVotingState()
    bot.voting = true
    bot.votePlayerCount = read.playerCount
    bot.voteStartTick = startTick
    bot.voteDelayTicks =
      if previousDelay >= 0:
        previousDelay
      else:
        bot.randomVoteDelay()
    bot.voteQueuedSusColor = previousQueuedSusColor
    bot.voteImposterChatDecided = previousImposterChatDecided
    bot.voteCursor = read.cursor
    bot.voteSelfSlot = read.selfSlot
    for i in 0 ..< read.playerCount:
      bot.voteSlots[i].colorIndex = read.slots[i].colorIndex
      bot.voteSlots[i].alive = read.slots[i].alive
    for i in 0 ..< min(bot.voteChoices.len, read.choices.len):
      bot.voteChoices[i] = read.choices[i]
    if read.selfSlot >= 0 and read.selfSlot < read.playerCount:
      bot.selfColorIndex = read.slots[read.selfSlot].colorIndex
    bot.voteChatLines.setLen(0)
    for entry in read.chat:
      for line in entry.lines:
        bot.voteChatLines.add VoteChatLine(
          speakerColor: entry.colorIndex,
          y: 0,
          text: line
        )
    bot.voteChatText = read.chatText
    bot.voteChatSusColor =
      if bot.voteSusColorAllowed(read.chatSusColor):
        read.chatSusColor
      else:
        VoteUnknown
    return true
  if bot.voting:
    bot.lastVoteFrame = ""
  bot.clearVotingState()
  false

proc addBodyMatch(matches: var seq[BodyMatch], x, y: int) =
  ## Adds one body match unless a nearby match already exists.
  for match in matches:
    if abs(match.x - x) <= BodySearchRadius and
        abs(match.y - y) <= BodySearchRadius:
      return
  matches.add(BodyMatch(x: x, y: y))

proc scanBodies(bot: var Bot) =
  ## Scans the current frame for visible dead bodies.
  bot.visibleBodies.setLen(0)
  for y in 0 .. ScreenHeight - bot.bodySprite.height:
    for x in 0 .. ScreenWidth - bot.bodySprite.width:
      if bot.matchesActorSprite(
        bot.bodySprite,
        x,
        y,
        false,
        BodyMaxMisses,
        BodyMinStablePixels,
        BodyMinTintPixels
      ):
        bot.visibleBodies.addBodyMatch(x, y)

proc addGhostMatch(matches: var seq[GhostMatch], x, y: int, flipH: bool) =
  ## Adds one ghost match unless a nearby match already exists.
  for match in matches:
    if abs(match.x - x) <= GhostSearchRadius and
        abs(match.y - y) <= GhostSearchRadius:
      return
  matches.add(GhostMatch(x: x, y: y, flipH: flipH))

proc scanGhosts(bot: var Bot) =
  ## Scans the current frame for visible ghosts.
  bot.visibleGhosts.setLen(0)
  for y in 0 .. ScreenHeight - bot.ghostSprite.height:
    for x in 0 .. ScreenWidth - bot.ghostSprite.width:
      if bot.matchesActorSprite(
        bot.ghostSprite,
        x,
        y,
        false,
        GhostMaxMisses,
        GhostMinStablePixels,
        GhostMinTintPixels
      ):
        bot.visibleGhosts.addGhostMatch(x, y, false)
      elif bot.matchesActorSprite(
        bot.ghostSprite,
        x,
        y,
        true,
        GhostMaxMisses,
        GhostMinStablePixels,
        GhostMinTintPixels
      ):
        bot.visibleGhosts.addGhostMatch(x, y, true)

proc scanTaskIcons(bot: var Bot) =
  ## Scans expected task icon positions for visible task icons.
  bot.visibleTaskIcons.setLen(0)
  if not bot.localized:
    return
  for task in bot.sim.tasks:
    let
      baseX = task.x + task.w div 2 - SpriteSize div 2 - bot.cameraX
      baseY = task.y - SpriteSize - 2 - bot.cameraY
    for bobY in -1 .. 1:
      let expectedY = baseY + bobY
      for dy in -TaskIconExpectedSearchRadius .. TaskIconExpectedSearchRadius:
        for dx in -TaskIconExpectedSearchRadius .. TaskIconExpectedSearchRadius:
          let
            x = baseX + dx
            y = expectedY + dy
          if matchesSprite(bot.unpacked, bot.taskSprite, x, y):
            bot.visibleTaskIcons.addIconMatch(x, y)

proc projectedRadarDot(
  bot: Bot,
  task: TaskStation
): tuple[visible: bool, x: int, y: int] =
  ## Projects an offscreen task icon to its expected radar edge pixel.
  if not bot.localized:
    return
  let
    iconSx = task.x + task.w div 2 - SpriteSize div 2 - bot.cameraX
    iconSy = task.y - SpriteSize - 2 - bot.cameraY
    iconX = iconSx + SpriteSize div 2
    iconY = iconSy + SpriteSize div 2
  if iconSx + SpriteSize > 0 and iconSy + SpriteSize > 0 and
      iconSx < ScreenWidth and iconSy < ScreenHeight:
    return (true, iconX, iconY)
  let
    px = float(bot.playerWorldX() + CollisionW div 2 - bot.cameraX)
    py = float(bot.playerWorldY() + CollisionH div 2 - bot.cameraY)
    dx = float(iconX) - px
    dy = float(iconY) - py
  if abs(dx) < 0.5 and abs(dy) < 0.5:
    return
  let
    minX = 0.0
    maxX = float(ScreenWidth - 1)
    minY = 0.0
    maxY = float(ScreenHeight - 1)
  var
    ex: float
    ey: float
  if abs(dx) > abs(dy):
    if dx > 0:
      ex = maxX
    else:
      ex = minX
    ey = py + dy * (ex - px) / dx
    ey = clamp(ey, minY, maxY)
  else:
    if dy > 0:
      ey = maxY
    else:
      ey = minY
    ex = px + dx * (ey - py) / dy
    ex = clamp(ex, minX, maxX)
  (false, int(ex), int(ey))

proc updateTaskGuesses(bot: var Bot) =
  ## Updates ephemeral task candidates from radar dots.
  if bot.taskStates.len != bot.sim.tasks.len:
    bot.taskStates = newSeq[TaskState](bot.sim.tasks.len)
  if bot.radarTasks.len != bot.sim.tasks.len:
    bot.radarTasks = newSeq[bool](bot.sim.tasks.len)
  if bot.checkoutTasks.len != bot.sim.tasks.len:
    bot.checkoutTasks = newSeq[bool](bot.sim.tasks.len)
  for i in 0 ..< bot.radarTasks.len:
    bot.radarTasks[i] = false
  if not bot.localized:
    return
  bot.scanRadarDots()
  if bot.radarDots.len == 0:
    return
  for i in 0 ..< bot.sim.tasks.len:
    let projected = bot.projectedRadarDot(bot.sim.tasks[i])
    if projected.visible:
      continue
    for dot in bot.radarDots:
      if abs(dot.x - projected.x) <= RadarMatchTolerance and
          abs(dot.y - projected.y) <= RadarMatchTolerance:
        bot.radarTasks[i] = true
        bot.checkoutTasks[i] = true
        if bot.taskStates[i] == TaskCompleted:
          bot.taskStates[i] = TaskMaybe

proc projectedTaskIcon(
  bot: Bot,
  task: TaskStation,
  bobY: int
): tuple[visible: bool, x: int, y: int] =
  ## Returns the expected screen position for a visible task icon.
  if not bot.localized:
    return
  let
    iconX = task.x + task.w div 2 - SpriteSize div 2 - bot.cameraX
    iconY = task.y - SpriteSize - 2 + bobY - bot.cameraY
  if iconX + SpriteSize < 0 or iconY + SpriteSize < 0 or
      iconX >= ScreenWidth or iconY >= ScreenHeight:
    return
  (true, iconX, iconY)

proc taskIconInspectRect(
  bot: Bot,
  task: TaskStation
): tuple[x: int, y: int, w: int, h: int] =
  ## Returns the expected screen rectangle for inspecting a task icon.
  (
    task.x + task.w div 2 - TaskIconInspectSize div 2 - bot.cameraX,
    task.y - TaskIconInspectSize - bot.cameraY,
    TaskIconInspectSize,
    TaskIconInspectSize
  )

proc taskIconRenderable(bot: Bot, task: TaskStation): bool =
  ## Returns true when the server could render the task icon.
  let
    center = task.taskCenter()
    sx = center.x - bot.cameraX
    sy = center.y - bot.cameraY
  sx >= 0 and sx < ScreenWidth and sy >= 0 and sy < ScreenHeight

proc taskIconClearAreaVisible(bot: Bot, task: TaskStation): bool =
  ## Returns true when the whole icon inspection area is visible.
  let rect = bot.taskIconInspectRect(task)
  rect.x >= TaskClearScreenMargin and
    rect.y >= TaskClearScreenMargin and
    rect.x + rect.w + TaskClearScreenMargin <= ScreenWidth and
    rect.y + rect.h + TaskClearScreenMargin <= ScreenHeight

proc taskIconMaybeVisibleFor(bot: Bot, task: TaskStation): bool =
  ## Returns true when expected icon pixels look plausibly present.
  let
    baseX = task.x + task.w div 2 - SpriteSize div 2 - bot.cameraX
    baseY = task.y - SpriteSize - 2 - bot.cameraY
  for bobY in -1 .. 1:
    let expectedY = baseY + bobY
    for dy in -TaskIconExpectedSearchRadius .. TaskIconExpectedSearchRadius:
      for dx in -TaskIconExpectedSearchRadius .. TaskIconExpectedSearchRadius:
        if maybeMatchesSprite(
          bot.unpacked,
          bot.taskSprite,
          baseX + dx,
          expectedY + dy
        ):
          return true

proc taskIconVisibleFor(bot: Bot, task: TaskStation): bool =
  ## Returns true if a visible task station has its icon on screen.
  for bobY in -1 .. 1:
    let projected = bot.projectedTaskIcon(task, bobY)
    if not projected.visible:
      continue
    for icon in bot.visibleTaskIcons:
      if abs(icon.x - projected.x) <= TaskIconSearchRadius and
          abs(icon.y - projected.y) <= TaskIconSearchRadius:
        return true

proc updateTaskIcons(bot: var Bot) =
  ## Updates task states from visible task icons.
  if bot.taskStates.len != bot.sim.tasks.len:
    bot.taskStates = newSeq[TaskState](bot.sim.tasks.len)
  if bot.taskIconMisses.len != bot.sim.tasks.len:
    bot.taskIconMisses = newSeq[int](bot.sim.tasks.len)
  if bot.checkoutTasks.len != bot.sim.tasks.len:
    bot.checkoutTasks = newSeq[bool](bot.sim.tasks.len)
  if not bot.localized:
    return
  bot.scanTaskIcons()
  for i in 0 ..< bot.sim.tasks.len:
    let task = bot.sim.tasks[i]
    if bot.taskIconVisibleFor(task):
      bot.taskStates[i] = TaskMandatory
      bot.taskIconMisses[i] = 0
    elif bot.taskHoldTicks == 0 and
        bot.taskIconClearAreaVisible(task) and
        not bot.taskIconMaybeVisibleFor(task) and
        (bot.radarTasks.len != bot.sim.tasks.len or not bot.radarTasks[i]) and
        bot.taskHoldIndex != i:
      if bot.taskStates[i] == TaskMandatory:
        inc bot.taskIconMisses[i]
        if bot.taskIconMisses[i] >= TaskIconMissThreshold:
          bot.taskStates[i] = TaskCompleted
          bot.checkoutTasks[i] = false
          bot.taskIconMisses[i] = 0
      elif bot.checkoutTasks[i]:
        inc bot.taskIconMisses[i]
        if bot.taskIconMisses[i] >= TaskIconMissThreshold:
          bot.checkoutTasks[i] = false
          bot.taskIconMisses[i] = 0
    else:
      bot.taskIconMisses[i] = 0

proc thought(bot: var Bot, text: string) =
  ## Stores changed bot thoughts for the GUI.
  if text != bot.lastThought:
    bot.lastThought = text

proc movementName(mask: uint8): string =
  ## Returns a compact movement label for one input mask.
  if (mask and ButtonLeft) != 0:
    return "left"
  if (mask and ButtonRight) != 0:
    return "right"
  if (mask and ButtonUp) != 0:
    return "up"
  if (mask and ButtonDown) != 0:
    return "down"
  "idle"

proc hasMovement(mask: uint8): bool =
  ## Returns true when an input mask contains directional movement.
  (mask and (ButtonUp or ButtonDown or ButtonLeft or ButtonRight)) != 0

proc updateMotionState(bot: var Bot) =
  ## Tracks current frame-to-frame player velocity.
  if not bot.localized:
    bot.haveMotionSample = false
    bot.velocityX = 0
    bot.velocityY = 0
    bot.stuckFrames = 0
    bot.jiggleTicks = 0
    return

  let
    x = bot.playerWorldX()
    y = bot.playerWorldY()
  if bot.haveMotionSample and bot.lastMask.hasMovement():
    bot.velocityX = x - bot.previousPlayerWorldX
    bot.velocityY = y - bot.previousPlayerWorldY
    let moved = abs(bot.velocityX) + abs(bot.velocityY)
    if moved == 0:
      inc bot.stuckFrames
    else:
      bot.stuckFrames = 0
    if bot.stuckFrames >= StuckFrameThreshold:
      bot.stuckFrames = 0
      bot.jiggleTicks = JiggleDuration
      bot.jiggleSide = 1 - bot.jiggleSide
  else:
    bot.velocityX = 0
    bot.velocityY = 0
    bot.stuckFrames = 0

  bot.haveMotionSample = true
  bot.previousPlayerWorldX = x
  bot.previousPlayerWorldY = y

proc applyJiggle(bot: var Bot, mask: uint8): uint8 =
  ## Adds a short perpendicular correction while keeping intent held.
  result = mask
  if bot.jiggleTicks <= 0 or not mask.hasMovement():
    return
  dec bot.jiggleTicks
  let
    vertical = (mask and (ButtonUp or ButtonDown)) != 0
    horizontal = (mask and (ButtonLeft or ButtonRight)) != 0
  if vertical and not horizontal:
    if bot.jiggleSide == 0:
      result = result or ButtonLeft
    else:
      result = result or ButtonRight
  elif horizontal and not vertical:
    if bot.jiggleSide == 0:
      result = result or ButtonUp
    else:
      result = result or ButtonDown
  elif bot.jiggleSide == 0:
    result = result or ButtonLeft
  else:
    result = result or ButtonRight

proc inputMaskSummary(mask: uint8): string =
  ## Returns a human-readable input mask.
  var parts: seq[string] = @[]
  if (mask and ButtonUp) != 0: parts.add("up")
  if (mask and ButtonDown) != 0: parts.add("down")
  if (mask and ButtonLeft) != 0: parts.add("left")
  if (mask and ButtonRight) != 0: parts.add("right")
  if (mask and ButtonA) != 0: parts.add("a")
  if (mask and ButtonB) != 0: parts.add("b")
  if (mask and ButtonSelect) != 0: parts.add("select")
  if parts.len == 0:
    return "idle"
  parts.join(", ")

proc taskStateCount(bot: Bot, state: TaskState): int =
  ## Returns the number of tasks in one state.
  for taskState in bot.taskStates:
    if taskState == state:
      inc result

proc radarTaskCount(bot: Bot): int =
  ## Returns the number of current radar task candidates.
  for radarTask in bot.radarTasks:
    if radarTask:
      inc result

proc checkoutTaskCount(bot: Bot): int =
  ## Returns the number of persistent checkout task candidates.
  for checkoutTask in bot.checkoutTasks:
    if checkoutTask:
      inc result

proc buttonFallbackReady(bot: Bot): bool =
  ## Returns true when home is the only useful remaining goal.
  bot.radarDots.len == 0 and
    bot.radarTaskCount() == 0 and
    bot.checkoutTaskCount() == 0 and
    bot.taskStateCount(TaskMandatory) == 0

proc rememberHome(bot: var Bot) =
  ## Records the first reliable round position as this bot's home.
  if not bot.localized or bot.interstitial:
    return
  bot.gameStarted = true
  if bot.homeSet:
    return
  bot.homeX = bot.playerWorldX()
  bot.homeY = bot.playerWorldY()
  bot.homeSet = true

proc roleName(role: BotRole): string =
  ## Returns a human-readable role name.
  case role
  of RoleUnknown: "unknown"
  of RoleCrewmate: "crewmate"
  of RoleImposter: "imposter"

proc knownImposterColor(bot: Bot, colorIndex: int): bool =
  ## Returns true if the color was shown as an imposter teammate.
  colorIndex >= 0 and
    colorIndex < bot.knownImposters.len and
    bot.knownImposters[colorIndex]

proc playerColorName(colorIndex: int): string =
  ## Returns the visible player color name.
  if colorIndex >= 0 and colorIndex < PlayerColorNames.len:
    PlayerColorNames[colorIndex]
  else:
    "unknown"

proc titlePlayerColorName(colorIndex: int): string =
  ## Returns the visible player color name with an uppercase first letter.
  result = playerColorName(colorIndex)
  if result.len > 0:
    result[0] = result[0].toUpperAscii()

proc voteTargetSafeForRole(bot: Bot, target: int): bool =
  ## Returns true when this role should be willing to vote for a target.
  if not bot.voteTargetCanBeSus(target):
    return false
  if bot.role == RoleImposter:
    let colorIndex = bot.voteSlots[target].colorIndex
    if bot.knownImposterColor(colorIndex):
      return false
  true

proc knownImposterSummary(bot: Bot): string =
  ## Returns a compact debug string for known imposter colors.
  for i, known in bot.knownImposters:
    if not known:
      continue
    if result.len > 0:
      result.add(", ")
    result.add(playerColorName(i))
  if result.len == 0:
    result = "none"

proc cameraLockName(lock: CameraLock): string =
  ## Returns a human-readable camera lock name.
  case lock
  of NoLock: "none"
  of LocalFrameMapLock: "local frame"
  of FrameMapLock: "frame map"

proc passable(bot: Bot, x, y: int): bool =
  ## Returns true when a collision-sized body can occupy a pixel.
  if x < 0 or y < 0 or x + CollisionW >= MapWidth or
      y + CollisionH >= MapHeight:
    return false
  for dy in 0 ..< CollisionH:
    for dx in 0 ..< CollisionW:
      if not bot.sim.walkMask[mapIndexSafe(x + dx, y + dy)]:
        return false
  true

proc heuristic(ax, ay, bx, by: int): int =
  ## Returns Manhattan distance for path search.
  abs(ax - bx) + abs(ay - by)

proc reconstructPath(
  parents: openArray[int],
  startIndex,
  goalIndex: int
): seq[PathStep] =
  ## Reconstructs a complete path from a parent table.
  var stepIndex = goalIndex
  while stepIndex != startIndex and stepIndex >= 0:
    result.add(PathStep(
      found: true,
      x: stepIndex mod tileWidth(),
      y: stepIndex div tileWidth()
    ))
    stepIndex = parents[stepIndex]
  for i in 0 ..< result.len div 2:
    swap(result[i], result[result.high - i])

proc findPath(bot: Bot, goalX, goalY: int): seq[PathStep] =
  ## Finds a complete A* pixel path toward a goal.
  let
    startX = bot.playerWorldX()
    startY = bot.playerWorldY()
    area = MapWidth * MapHeight
    startIndex = mapIndexSafe(startX, startY)
    goalIndex = mapIndexSafe(goalX, goalY)
  if not bot.passable(startX, startY) or not bot.passable(goalX, goalY):
    return
  var
    parents = newSeq[int](area)
    costs = newSeq[int](area)
    closed = newSeq[bool](area)
    openSet: HeapQueue[PathNode]
  for i in 0 ..< area:
    parents[i] = -2
    costs[i] = high(int)
  parents[startIndex] = -1
  costs[startIndex] = 0
  openSet.push(PathNode(
    priority: heuristic(startX, startY, goalX, goalY),
    index: startIndex
  ))
  while openSet.len > 0:
    let current = openSet.pop()
    if closed[current.index]:
      continue
    if current.index == goalIndex:
      return reconstructPath(parents, startIndex, goalIndex)
    closed[current.index] = true
    let
      x = current.index mod tileWidth()
      y = current.index div tileWidth()
    for delta in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
      let
        nx = x + delta[0]
        ny = y + delta[1]
      if not bot.passable(nx, ny):
        continue
      let nextIndex = mapIndexSafe(nx, ny)
      if closed[nextIndex]:
        continue
      let newCost = costs[current.index] + 1
      if newCost >= costs[nextIndex]:
        continue
      costs[nextIndex] = newCost
      parents[nextIndex] = current.index
      openSet.push(PathNode(
        priority: newCost + heuristic(nx, ny, goalX, goalY),
        index: nextIndex
      ))

proc pathDistance(bot: Bot, goalX, goalY: int): int =
  ## Returns the real A* path distance to a goal.
  if bot.playerWorldX() == goalX and bot.playerWorldY() == goalY:
    return 0
  let path = bot.findPath(goalX, goalY)
  if path.len == 0:
    return high(int)
  path.len

proc goalDistance(bot: Bot, goalX, goalY: int): int =
  ## Returns the distance metric for choosing the next goal.
  if bot.isGhost:
    return heuristic(bot.playerWorldX(), bot.playerWorldY(), goalX, goalY)
  bot.pathDistance(goalX, goalY)

proc taskGoalFor(
  bot: Bot,
  index: int,
  state: TaskState
): tuple[found: bool, index: int, x: int, y: int, name: string, state: TaskState] =
  ## Returns a reachable task goal inside one task rectangle.
  if index < 0 or index >= bot.sim.tasks.len:
    return
  let
    task = bot.sim.tasks[index]
    center = task.taskCenter()
  var
    bestDistance = high(int)
    bestX = 0
    bestY = 0
  proc iconVisibleAt(x, y: int): bool =
    let
      cameraX = x - PlayerWorldOffX
      cameraY = y - PlayerWorldOffY
      iconWorldX = task.x + task.w div 2 - SpriteSize div 2
      iconWorldY = task.y - SpriteSize - 2
    for bobY in -1 .. 1:
      let
        iconX = iconWorldX - cameraX
        iconY = iconWorldY + bobY - cameraY
      if iconX < 0 or iconY < 0 or
          iconX + SpriteSize > ScreenWidth or
          iconY + SpriteSize > ScreenHeight:
        return false
    true
  template considerRange(x0, y0, x1, y1: int, requireIcon: bool) =
    for y in max(task.y, y0) ..< min(task.y + task.h, y1):
      for x in max(task.x, x0) ..< min(task.x + task.w, x1):
        if not bot.passable(x, y):
          continue
        if requireIcon and not iconVisibleAt(x, y):
          continue
        let distance = heuristic(center.x, center.y, x, y)
        if distance < bestDistance:
          bestDistance = distance
          bestX = x
          bestY = y
  considerRange(
    task.x + TaskInnerMargin,
    task.y + TaskInnerMargin,
    task.x + task.w - TaskInnerMargin,
    task.y + task.h - TaskInnerMargin,
    true
  )
  if bestDistance == high(int):
    considerRange(
      task.x + TaskInnerMargin,
      task.y + TaskInnerMargin,
      task.x + task.w - TaskInnerMargin,
      task.y + task.h - TaskInnerMargin,
      false
    )
  if bestDistance == high(int):
    considerRange(
      task.x,
      task.y,
      task.x + task.w,
      task.y + task.h,
      false
    )
  if bestDistance == high(int):
    return
  (true, index, bestX, bestY, task.name, state)

proc buttonGoal(
  bot: Bot
): tuple[found: bool, index: int, x: int, y: int, name: string, state: TaskState] =
  ## Returns a reachable point inside the emergency button rectangle.
  let
    button = bot.sim.gameMap.button
    centerX = button.x + button.w div 2
    centerY = button.y + button.h div 2
  var
    bestDistance = high(int)
    bestX = 0
    bestY = 0
  for y in button.y ..< button.y + button.h:
    for x in button.x ..< button.x + button.w:
      if not bot.passable(x, y):
        continue
      let distance = heuristic(centerX, centerY, x, y)
      if distance < bestDistance:
        bestDistance = distance
        bestX = x
        bestY = y
  if bestDistance == high(int):
    return
  (true, -1, bestX, bestY, "Button", TaskMaybe)

proc homeGoal(
  bot: Bot
): tuple[found: bool, index: int, x: int, y: int, name: string, state: TaskState] =
  ## Returns this bot's remembered cafeteria home point.
  if not bot.homeSet:
    return bot.buttonGoal()
  if bot.isGhost or bot.passable(bot.homeX, bot.homeY):
    return (true, -1, bot.homeX, bot.homeY, "Home", TaskMaybe)
  var
    bestDistance = high(int)
    bestX = 0
    bestY = 0
  for y in max(0, bot.homeY - HomeSearchRadius) ..
      min(MapHeight - 1, bot.homeY + HomeSearchRadius):
    for x in max(0, bot.homeX - HomeSearchRadius) ..
        min(MapWidth - 1, bot.homeX + HomeSearchRadius):
      if not bot.passable(x, y):
        continue
      let distance = heuristic(bot.homeX, bot.homeY, x, y)
      if distance < bestDistance:
        bestDistance = distance
        bestX = x
        bestY = y
  if bestDistance == high(int):
    return bot.buttonGoal()
  (true, -1, bestX, bestY, "Home", TaskMaybe)

proc fakeTargetCount(bot: Bot): int =
  ## Returns the number of imposter fake target areas.
  bot.sim.tasks.len + 1

proc fakeTargetGoalFor(
  bot: Bot,
  index: int
): tuple[found: bool, index: int, x: int, y: int, name: string, state: TaskState] =
  ## Returns an imposter fake goal for a task or the button.
  if index == bot.sim.tasks.len:
    return bot.buttonGoal()
  bot.taskGoalFor(index, TaskMaybe)

proc randomFakeTargetIndex(bot: var Bot): int =
  ## Returns a random imposter fake target index.
  let count = bot.fakeTargetCount()
  if count == 0:
    return -1
  bot.rng.rand(count - 1)

proc fakeTargetCenter(
  bot: Bot,
  index: int
): tuple[x: int, y: int] =
  ## Returns the center point for an imposter fake target.
  if index == bot.sim.tasks.len:
    let button = bot.sim.gameMap.button
    return (button.x + button.w div 2, button.y + button.h div 2)
  bot.sim.tasks[index].taskCenter()

proc farthestFakeTargetIndexFrom(bot: Bot, originX, originY: int): int =
  ## Returns the fake target farthest from an origin point.
  var bestDistance = low(int)
  result = -1
  for i in 0 ..< bot.fakeTargetCount():
    let center = bot.fakeTargetCenter(i)
    let distance = heuristic(originX, originY, center.x, center.y)
    if distance > bestDistance:
      bestDistance = distance
      result = i

proc farthestFakeTargetIndex(bot: Bot): int =
  ## Returns the fake target farthest from the current player location.
  bot.farthestFakeTargetIndexFrom(bot.playerWorldX(), bot.playerWorldY())

proc visibleCrewmateWorld(
  bot: Bot,
  crewmate: CrewmateMatch
): tuple[x: int, y: int] =
  ## Converts one visible crewmate match into world coordinates.
  (
    bot.cameraX + crewmate.x + SpriteDrawOffX,
    bot.cameraY + crewmate.y + SpriteDrawOffY
  )

proc loneVisibleCrewmate(
  bot: Bot
): tuple[found: bool, crewmate: CrewmateMatch] =
  ## Returns the only visible crewmate not known as an imposter.
  for crewmate in bot.visibleCrewmates:
    if bot.knownImposterColor(crewmate.colorIndex):
      continue
    if result.found:
      result.found = false
      return
    result.found = true
    result.crewmate = crewmate

proc visibleBodyWorld(bot: Bot, body: BodyMatch): tuple[x: int, y: int] =
  ## Converts one visible body match into world coordinates.
  (
    bot.cameraX + body.x + SpriteDrawOffX,
    bot.cameraY + body.y + SpriteDrawOffY
  )

proc nearestBody(bot: Bot): tuple[found: bool, x: int, y: int] =
  ## Returns the nearest visible body in world coordinates.
  var bestDistance = high(int)
  for body in bot.visibleBodies:
    let world = bot.visibleBodyWorld(body)
    let distance = heuristic(
      bot.playerWorldX(),
      bot.playerWorldY(),
      world.x,
      world.y
    )
    if distance < bestDistance:
      bestDistance = distance
      result = (true, world.x, world.y)

proc sameBody(ax, ay, bx, by: int): bool =
  ## Returns true when two body sightings are probably the same body.
  if bx == low(int) or by == low(int):
    return false
  heuristic(ax, ay, bx, by) <= BodySearchRadius + 4

proc suspectedColorFrom(
  bot: Bot,
  ticks: openArray[int]
): tuple[found: bool, name: string, tick: int, colorIndex: int] =
  ## Returns the most recently seen valid crewmate color.
  var bestTick = 0
  for i, tick in ticks:
    if i == bot.selfColorIndex:
      continue
    if bot.knownImposterColor(i):
      continue
    if tick > bestTick and i < PlayerColorNames.len:
      bestTick = tick
      result = (true, playerColorName(i), tick, i)

proc suspectedColor(
  bot: Bot
): tuple[found: bool, name: string, tick: int, colorIndex: int] =
  ## Returns the most recently seen crewmate color.
  bot.suspectedColorFrom(bot.lastSeenTicks)

proc bodySuspectedColor(
  bot: Bot
): tuple[found: bool, name: string, tick: int, colorIndex: int] =
  ## Returns the most recently seen crewmate around the reported body.
  result = bot.suspectedColorFrom(bot.bodySeenTicks)
  if not result.found:
    result = bot.suspectedColor()

proc suspectSummary(bot: Bot): string =
  ## Returns a short debug summary for the current suspect.
  let suspect = bot.suspectedColor()
  if not suspect.found:
    return "none"
  suspect.name & " seen=" & $suspect.tick

proc bodyRoomMessage(bot: Bot, x, y: int): string =
  ## Builds a short chat line that names a body's room.
  let room = bot.roomNameAt(x + CollisionW div 2, y + CollisionH div 2)
  let suspect = bot.bodySuspectedColor()
  result =
    if room == "unknown":
      "body"
    else:
      "body in " & room
  if suspect.found:
    result.add(" sus ")
    result.add(suspect.name)

proc rememberBodySuspects(bot: var Bot) =
  ## Stores the current seen-player ticks for voting after a body report.
  for i in 0 ..< bot.bodySeenTicks.len:
    bot.bodySeenTicks[i] = bot.lastSeenTicks[i]

proc queueBodySeen(bot: var Bot, x, y: int) =
  ## Stores the room for a discovered body until voting opens.
  if sameBody(x, y, bot.lastBodySeenX, bot.lastBodySeenY):
    return
  bot.lastBodySeenX = x
  bot.lastBodySeenY = y
  bot.rememberBodySuspects()
  bot.pendingChat = bot.bodyRoomMessage(x, y)

proc queueBodyReport(bot: var Bot, x, y: int) =
  ## Stores the room for a reported body until voting opens.
  if sameBody(x, y, bot.lastBodyReportX, bot.lastBodyReportY):
    return
  bot.lastBodyReportX = x
  bot.lastBodyReportY = y
  bot.rememberBodySuspects()
  bot.pendingChat = bot.bodyRoomMessage(x, y)

proc voteTargetName(bot: Bot, target: int): string =
  ## Returns a short display name for a voting target.
  if target == VoteSkip:
    return "skip"
  if target >= 0 and target < bot.votePlayerCount:
    return playerColorName(bot.voteSlots[target].colorIndex)
  "unknown"

proc voteSusTargetName(bot: Bot): string =
  ## Returns the current living non-self sus target name.
  if bot.voteTargetCanBeSus(bot.voteTarget):
    return bot.voteTargetName(bot.voteTarget)
  "none"

proc voteSummary(bot: Bot): string =
  ## Returns a compact summary of parsed votes.
  for i, choice in bot.voteChoices:
    if choice == VoteUnknown:
      continue
    if result.len > 0:
      result.add(", ")
    result.add(playerColorName(i))
    result.add("->")
    result.add(bot.voteTargetName(choice))
  if result.len == 0:
    result = "none"

proc voteChatSpeakerName(line: VoteChatLine): string =
  ## Returns a display name for one parsed chat speaker.
  playerColorName(line.speakerColor)

proc voteBodyLocationText(text: string): string =
  ## Extracts a visible body location from normalized chat text.
  let normalized = text.normalizeChatText()
  let marker = "body in "
  let startIndex = normalized.find(marker)
  if startIndex >= 0:
    let
      bodyStart = startIndex + marker.len
      susIndex = normalized.find(" sus ", bodyStart)
      bodyEnd =
        if susIndex >= 0:
          susIndex
        else:
          normalized.len
    result = normalized[bodyStart ..< bodyEnd].strip()
    if result.len == 0:
      result = "unknown"
    return
  if (" " & normalized & " ").contains(" body "):
    return "unknown"
  "none"

proc voteSeenLine(bot: Bot, index: int): string =
  ## Builds one player status line from the voting grid.
  let slot = bot.voteSlots[index]
  result = "player "
  result.add(playerColorName(slot.colorIndex))
  if slot.alive:
    result.add(" is alive")
  else:
    result.add(" is dead")
  if index == bot.voteSelfSlot:
    result.add(" (me)")

proc addVotingFrameVotes(bot: Bot, text: var string) =
  ## Adds one plain vote line for each player with a parsed vote.
  var found = false
  for i, choice in bot.voteChoices:
    if choice == VoteUnknown:
      continue
    text.add(playerColorName(i))
    text.add(" voted against ")
    text.add(bot.voteTargetName(choice))
    text.add('\n')
    found = true
  if not found:
    text.add("votes: none\n")

proc votingAsciiFrame(bot: Bot): string =
  ## Builds the plain text voting frame for LLM-style reasoning.
  result = "--- voting ---\n"
  for i in 0 ..< bot.votePlayerCount:
    result.add(bot.voteSeenLine(i))
    result.add('\n')
  if bot.voteChatLines.len > 0:
    result.add("chat:\n")
    for line in bot.voteChatLines:
      result.add(line.voteChatSpeakerName())
      result.add(": ")
      result.add(line.text)
      result.add('\n')
  let bodyLocation = voteBodyLocationText(bot.voteChatText)
  if bodyLocation != "none":
    result.add("body in ")
    result.add(bodyLocation)
    result.add('\n')
  result.add("sus ")
  result.add(bot.voteSusTargetName())
  result.add('\n')
  bot.addVotingFrameVotes(result)
  result.add("vote target: ")
  result.add(bot.voteTargetName(bot.voteTarget))
  result.add('\n')
  result.add("--- end voting ---")

proc printVotingFrame(bot: var Bot) =
  ## Prints the voting frame when pixel OCR changes.
  let frame = bot.votingAsciiFrame()
  if frame == bot.lastVoteFrame:
    return
  bot.lastVoteFrame = frame
  echo frame

proc selfVoteChoice(bot: Bot): int =
  ## Returns the parsed vote choice for the local player.
  if bot.selfColorIndex >= 0 and bot.selfColorIndex < bot.voteChoices.len:
    return bot.voteChoices[bot.selfColorIndex]
  if bot.voteSelfSlot >= 0 and bot.voteSelfSlot < bot.votePlayerCount:
    let colorIndex = bot.voteSlots[bot.voteSelfSlot].colorIndex
    if colorIndex >= 0 and colorIndex < bot.voteChoices.len:
      return bot.voteChoices[colorIndex]
  VoteUnknown

proc nextVoteSelectable(bot: Bot, cursor, direction: int): int =
  ## Returns the next selectable voting cursor slot.
  let total = bot.votePlayerCount + 1
  if total <= 0:
    return VoteUnknown
  var cur = cursor
  for step in 1 .. total:
    cur = (cur + direction + total) mod total
    if cur == bot.votePlayerCount:
      return cur
    if cur >= 0 and cur < bot.votePlayerCount and bot.voteSlots[cur].alive:
      return cur
  VoteUnknown

proc voteStepsTo(bot: Bot, target, direction: int): int =
  ## Counts cursor steps in one direction to a target.
  if bot.voteCursor == VoteUnknown:
    return high(int)
  var cur = bot.voteCursor
  for step in 0 .. bot.votePlayerCount + 1:
    if cur == target:
      return step
    cur = bot.nextVoteSelectable(cur, direction)
    if cur == VoteUnknown:
      return high(int)
  high(int)

proc voteMoveDirection(bot: Bot, target: int): int =
  ## Chooses the shortest voting cursor direction toward a target.
  let
    leftSteps = bot.voteStepsTo(target, -1)
    rightSteps = bot.voteStepsTo(target, 1)
  if leftSteps < rightSteps:
    -1
  else:
    1

proc seenVotingTargetFrom(bot: Bot, ticks: openArray[int]): int =
  ## Returns the latest seen living non-self voting target.
  result = VoteUnknown
  var bestTick = 0
  for i, tick in ticks:
    if i >= PlayerColorNames.len:
      continue
    if bot.knownImposterColor(i):
      continue
    let slot = bot.voteSlotForColor(i)
    if not bot.voteTargetSafeForRole(slot):
      continue
    if tick > bestTick:
      bestTick = tick
      result = slot

proc revengeVotingTarget(bot: Bot): int =
  ## Returns a living non-self voter who has voted for this bot.
  if bot.voteSelfSlot < 0:
    return VoteUnknown
  for i, choice in bot.voteChoices:
    if choice != bot.voteSelfSlot:
      continue
    let slot = bot.voteSlotForColor(i)
    if bot.voteTargetSafeForRole(slot):
      return slot
  VoteUnknown

proc imposterBandwagonTarget(bot: Bot): int =
  ## Returns a voted non-imposter target that an imposter can pile onto.
  if bot.role != RoleImposter:
    return VoteUnknown
  var counts: array[MaxPlayers, int]
  for i, choice in bot.voteChoices:
    if i == bot.selfColorIndex:
      continue
    if choice < 0 or choice >= bot.votePlayerCount:
      continue
    if not bot.voteTargetSafeForRole(choice):
      continue
    inc counts[choice]
  var bestCount = 0
  result = VoteUnknown
  for target in 0 ..< bot.votePlayerCount:
    if counts[target] > bestCount:
      bestCount = counts[target]
      result = target

proc queuedSusVotingTarget(bot: Bot): int =
  ## Returns the still-hidden sus chat target queued by this bot.
  if bot.voteQueuedSusColor == VoteUnknown:
    return VoteUnknown
  let slot = bot.voteSlotForColor(bot.voteQueuedSusColor)
  if bot.voteTargetSafeForRole(slot):
    return slot
  VoteUnknown

proc randomCrewmateSusColor(bot: var Bot): int =
  ## Chooses a random living crewmate color for imposter sus chat.
  var colors: seq[int]
  for i in 0 ..< bot.votePlayerCount:
    if not bot.voteTargetSafeForRole(i):
      continue
    colors.add(bot.voteSlots[i].colorIndex)
  if colors.len == 0:
    return VoteUnknown
  colors[bot.rng.rand(colors.high)]

proc maybeQueueImposterSusChat(bot: var Bot) =
  ## Sometimes queues one fake sus chat line during an imposter vote.
  if bot.role != RoleImposter:
    return
  if bot.voteImposterChatDecided:
    return
  bot.voteImposterChatDecided = true
  if bot.pendingChat.len > 0:
    return
  if bot.rng.rand(99) >= ImposterSusChatPercent:
    return
  let colorIndex = bot.randomCrewmateSusColor()
  if colorIndex == VoteUnknown:
    return
  bot.voteQueuedSusColor = colorIndex
  bot.pendingChat = titlePlayerColorName(colorIndex) & " sus"

proc desiredVotingTarget(bot: Bot): int =
  ## Chooses the voting target from current suspicion or skip.
  let revengeTarget = bot.revengeVotingTarget()
  if revengeTarget != VoteUnknown:
    return revengeTarget
  let bandwagonTarget = bot.imposterBandwagonTarget()
  if bandwagonTarget != VoteUnknown:
    return bandwagonTarget
  let queuedSusTarget = bot.queuedSusVotingTarget()
  if queuedSusTarget != VoteUnknown:
    return queuedSusTarget
  let ownSusTarget = bot.ownSusVotingTarget()
  if bot.voteTargetSafeForRole(ownSusTarget):
    return ownSusTarget
  if bot.voteChatSusColor >= 0:
    let slot = bot.voteSlotForColor(bot.voteChatSusColor)
    if bot.voteTargetSafeForRole(slot):
      return slot
  let bodyTarget = bot.seenVotingTargetFrom(bot.bodySeenTicks)
  if bodyTarget != VoteUnknown:
    return bodyTarget
  let seenTarget = bot.seenVotingTargetFrom(bot.lastSeenTicks)
  if seenTarget != VoteUnknown:
    return seenTarget
  bot.votePlayerCount

proc decideVotingMask(bot: var Bot): uint8 =
  ## Chooses voting-screen input from parsed vote state.
  bot.hasGoal = false
  bot.hasPathStep = false
  bot.path.setLen(0)
  let ownVote = bot.selfVoteChoice()
  if ownVote == VoteUnknown:
    bot.maybeQueueImposterSusChat()
  bot.voteTarget = bot.desiredVotingTarget()
  let instantVote =
    bot.voteTarget >= 0 and bot.ownSusVotingTarget() == bot.voteTarget
  bot.printVotingFrame()
  if ownVote != VoteUnknown:
    bot.desiredMask = 0
    bot.controllerMask = 0
    bot.intent = "voted " & bot.voteTargetName(ownVote)
    bot.thought(bot.intent)
    return 0
  if bot.voteCursor != bot.voteTarget:
    let direction = bot.voteMoveDirection(bot.voteTarget)
    let mask =
      if direction < 0:
        ButtonLeft
      else:
        ButtonRight
    bot.desiredMask =
      if bot.lastMask == mask:
        0
      else:
        mask
    bot.controllerMask = bot.desiredMask
    bot.intent = "voting cursor to " & bot.voteTargetName(bot.voteTarget)
    bot.thought(bot.intent)
    return bot.desiredMask
  let listenedTicks =
    if bot.voteStartTick >= 0:
      bot.frameTick - bot.voteStartTick
    else:
      0
  if bot.voteDelayTicks < 0:
    bot.voteDelayTicks = bot.randomVoteDelay()
  if not instantVote and listenedTicks < bot.voteDelayTicks:
    bot.desiredMask = 0
    bot.controllerMask = 0
    bot.intent = "ready, listening in vote chat " &
      $listenedTicks & "/" & $bot.voteDelayTicks
    bot.thought(bot.intent)
    return 0
  bot.desiredMask =
    if bot.lastMask == ButtonA:
      0
    else:
      ButtonA
  bot.controllerMask = bot.desiredMask
  bot.intent = "voting for " & bot.voteTargetName(bot.voteTarget)
  bot.thought(bot.intent)
  bot.desiredMask

proc inReportRange(bot: Bot, targetX, targetY: int): bool =
  ## Returns true when the target point is in report range.
  let
    ax = bot.playerWorldX() + CollisionW div 2
    ay = bot.playerWorldY() + CollisionH div 2
    bx = targetX + CollisionW div 2
    by = targetY + CollisionH div 2
    dx = ax - bx
    dy = ay - by
  dx * dx + dy * dy <= bot.sim.config.reportRange * bot.sim.config.reportRange

proc inKillRange(bot: Bot, targetX, targetY: int): bool =
  ## Returns true when the target point is in imposter kill range.
  let
    ax = bot.playerWorldX() + CollisionW div 2
    ay = bot.playerWorldY() + CollisionH div 2
    bx = targetX + CollisionW div 2
    by = targetY + CollisionH div 2
    dx = ax - bx
    dy = ay - by
  dx * dx + dy * dy <= bot.sim.config.killRange * bot.sim.config.killRange

proc nearestTaskGoal(
  bot: Bot
): tuple[found: bool, index: int, x: int, y: int, name: string, state: TaskState] =
  ## Returns the closest known active task station center.
  var bestDistance = high(int)
  for i in 0 ..< bot.sim.tasks.len:
    if not bot.taskIconVisibleFor(bot.sim.tasks[i]):
      continue
    let goal = bot.taskGoalFor(i, TaskMandatory)
    if not goal.found:
      continue
    let distance = bot.goalDistance(goal.x, goal.y)
    if distance < bestDistance:
      bestDistance = distance
      result = goal
  if result.found:
    return
  if bot.goalIndex >= 0 and
      bot.goalIndex < bot.sim.tasks.len and
      bot.taskStates.len == bot.sim.tasks.len and
      bot.taskStates[bot.goalIndex] == TaskMandatory:
    let goal = bot.taskGoalFor(bot.goalIndex, TaskMandatory)
    if goal.found:
      return goal
  bestDistance = high(int)
  for i in 0 ..< bot.sim.tasks.len:
    if bot.taskStates.len == bot.sim.tasks.len and
        bot.taskStates[i] != TaskMandatory:
      continue
    let goal = bot.taskGoalFor(i, TaskMandatory)
    if not goal.found:
      continue
    let distance = bot.goalDistance(goal.x, goal.y)
    if distance < bestDistance:
      bestDistance = distance
      result = goal
  if result.found:
    return
  if bot.goalIndex >= 0 and
      bot.goalIndex < bot.sim.tasks.len and
      bot.taskStates.len == bot.sim.tasks.len and
      bot.taskStates[bot.goalIndex] != TaskCompleted and
      bot.checkoutTasks.len == bot.sim.tasks.len and
      bot.checkoutTasks[bot.goalIndex]:
    let goal = bot.taskGoalFor(bot.goalIndex, TaskMaybe)
    if goal.found:
      return goal
  bestDistance = high(int)
  for i in 0 ..< bot.sim.tasks.len:
    if bot.checkoutTasks.len != bot.sim.tasks.len or
        not bot.checkoutTasks[i]:
      continue
    if bot.taskStates.len == bot.sim.tasks.len and
        bot.taskStates[i] == TaskCompleted:
      continue
    let goal = bot.taskGoalFor(i, TaskMaybe)
    if not goal.found:
      continue
    let distance = bot.goalDistance(goal.x, goal.y)
    if distance < bestDistance:
      bestDistance = distance
      result = goal
  if result.found:
    return
  if bot.goalIndex >= 0 and
      bot.goalIndex < bot.sim.tasks.len and
      bot.radarTasks.len == bot.sim.tasks.len and
      bot.radarTasks[bot.goalIndex]:
    let goal = bot.taskGoalFor(bot.goalIndex, TaskMaybe)
    if goal.found:
      return goal
  bestDistance = high(int)
  for i in 0 ..< bot.sim.tasks.len:
    if bot.radarTasks.len != bot.sim.tasks.len or not bot.radarTasks[i]:
      continue
    let goal = bot.taskGoalFor(i, TaskMaybe)
    if not goal.found:
      continue
    let distance = bot.goalDistance(goal.x, goal.y)
    if distance < bestDistance:
      bestDistance = distance
      result = goal
  if result.found:
    return
  if bot.buttonFallbackReady():
    return bot.homeGoal()

proc coastDistance(velocity: int): int =
  ## Returns how many pixels current velocity will carry without input.
  var speed = abs(velocity)
  for _ in 0 ..< CoastLookaheadTicks:
    if speed <= 0:
      break
    result += speed
    speed = (speed * FrictionNum) div FrictionDen

proc shouldCoast(delta, velocity: int): bool =
  ## Returns true when existing velocity should reach the target.
  if delta > 0 and velocity > 0:
    return delta <= coastDistance(velocity) + CoastArrivalPadding
  if delta < 0 and velocity < 0:
    return -delta <= coastDistance(velocity) + CoastArrivalPadding

proc axisMask(delta, velocity: int, negativeMask, positiveMask: uint8): uint8 =
  ## Returns steering for one axis with coasting and braking.
  if delta > SteerDeadband:
    if shouldCoast(delta, velocity):
      return 0
    if velocity > 1 and delta <= abs(velocity) + BrakeDeadband:
      return negativeMask
    return positiveMask
  if delta < -SteerDeadband:
    if shouldCoast(delta, velocity):
      return 0
    if velocity < -1 and -delta <= abs(velocity) + BrakeDeadband:
      return positiveMask
    return negativeMask
  if velocity > 0:
    return negativeMask
  if velocity < 0:
    return positiveMask
  0

proc preciseAxisMask(delta, velocity: int, negativeMask, positiveMask: uint8): uint8 =
  ## Returns exact final-approach steering with coasting.
  if delta > 0:
    if shouldCoast(delta, velocity):
      return 0
    if velocity > 1 and delta <= abs(velocity) + BrakeDeadband:
      return negativeMask
    return positiveMask
  if delta < 0:
    if shouldCoast(delta, velocity):
      return 0
    if velocity < -1 and -delta <= abs(velocity) + BrakeDeadband:
      return positiveMask
    return negativeMask
  if velocity > 0:
    return negativeMask
  if velocity < 0:
    return positiveMask
  0

proc maskForWaypoint(bot: Bot, waypoint: PathStep): uint8 =
  ## Converts a lookahead waypoint into a momentum-aware controller mask.
  if not waypoint.found:
    return 0
  let
    dx = waypoint.x - bot.playerWorldX()
    dy = waypoint.y - bot.playerWorldY()
  result = result or axisMask(dx, bot.velocityX, ButtonLeft, ButtonRight)
  result = result or axisMask(dy, bot.velocityY, ButtonUp, ButtonDown)

proc preciseMaskForGoal(bot: Bot, goalX, goalY: int): uint8 =
  ## Converts a nearby goal into exact final-approach steering.
  let
    dx = goalX - bot.playerWorldX()
    dy = goalY - bot.playerWorldY()
  result = result or preciseAxisMask(dx, bot.velocityX, ButtonLeft, ButtonRight)
  result = result or preciseAxisMask(dy, bot.velocityY, ButtonUp, ButtonDown)

proc choosePathStep(bot: Bot): PathStep =
  ## Returns a short lookahead waypoint from the current path.
  if bot.path.len == 0:
    return
  let index = min(bot.path.high, PathLookahead)
  bot.path[index]

proc taskReady(bot: Bot, task: TaskStation): bool =
  ## Returns true when the player can safely hold action for a task.
  let
    x = bot.playerWorldX()
    y = bot.playerWorldY()
    innerX0 = task.x + TaskInnerMargin
    innerY0 = task.y + TaskInnerMargin
    innerX1 = task.x + task.w - TaskInnerMargin
    innerY1 = task.y + task.h - TaskInnerMargin
  if x < innerX0 or x >= innerX1 or y < innerY0 or y >= innerY1:
    return false
  abs(bot.velocityX) + abs(bot.velocityY) <= 1

proc taskReadyAtGoal(bot: Bot, index, goalX, goalY: int): bool =
  ## Returns true when a task can be held at a selected goal.
  if index < 0 or index >= bot.sim.tasks.len:
    return false
  let
    task = bot.sim.tasks[index]
    x = bot.playerWorldX()
    y = bot.playerWorldY()
  if x < task.x or x >= task.x + task.w or
      y < task.y or y >= task.y + task.h:
    return false
  if abs(bot.velocityX) + abs(bot.velocityY) > 1:
    return false
  bot.taskReady(task) or heuristic(x, y, goalX, goalY) <= 1

proc taskGoalReady(
  bot: Bot,
  goal: tuple[
    found: bool,
    index: int,
    x: int,
    y: int,
    name: string,
    state: TaskState
  ]
): bool =
  ## Returns true when the selected goal is ready for task action.
  if not goal.found:
    return false
  bot.taskReadyAtGoal(goal.index, goal.x, goal.y)

proc holdTaskAction(bot: var Bot, name: string): uint8 =
  ## Holds only the action button while completing a task.
  bot.intent = "doing task at " & name & " hold=" & $bot.taskHoldTicks
  bot.desiredMask = ButtonA
  bot.controllerMask = ButtonA
  bot.hasPathStep = false
  bot.path.setLen(0)
  if bot.taskHoldTicks > 0:
    dec bot.taskHoldTicks
  if bot.taskHoldTicks == 0 and
      bot.taskHoldIndex >= 0 and
      bot.taskHoldIndex < bot.taskStates.len:
    let task = bot.sim.tasks[bot.taskHoldIndex]
    if not bot.taskIconVisibleFor(task) and bot.taskIconClearAreaVisible(task):
      bot.taskStates[bot.taskHoldIndex] = TaskCompleted
      if bot.checkoutTasks.len == bot.sim.tasks.len:
        bot.checkoutTasks[bot.taskHoldIndex] = false
    else:
      bot.taskStates[bot.taskHoldIndex] = TaskMandatory
    bot.taskHoldIndex = -1
  bot.thought("at task " & name & ", holding action")
  ButtonA

proc reportBodyAction(bot: var Bot, x, y: int): uint8 =
  ## Presses action to report a visible dead body.
  bot.intent = "reporting dead body"
  bot.desiredMask = ButtonA
  bot.controllerMask = ButtonA
  bot.hasPathStep = false
  bot.path.setLen(0)
  bot.taskHoldTicks = 0
  bot.taskHoldIndex = -1
  bot.queueBodyReport(x, y)
  bot.thought("reporting dead body")
  ButtonA

proc navigateToPoint(
  bot: var Bot,
  x,
  y: int,
  name: string,
  preciseRadius = TaskPreciseApproachRadius
): uint8 =
  ## Navigates toward one world point and returns the input mask.
  bot.hasGoal = true
  bot.goalX = x
  bot.goalY = y
  bot.goalName = name
  if bot.isGhost:
    bot.path.setLen(0)
    bot.hasPathStep = false
    bot.astarMicros = 0
    bot.intent = "ghost direct to " & name
    bot.desiredMask = bot.preciseMaskForGoal(x, y)
  else:
    let astarStart = getMonoTime()
    bot.path = bot.findPath(x, y)
    bot.astarMicros = int((getMonoTime() - astarStart).inMicroseconds)
    bot.pathStep = bot.choosePathStep()
    bot.hasPathStep = bot.pathStep.found
    bot.intent = "A* to " & name & " path=" & $bot.path.len
    if heuristic(bot.playerWorldX(), bot.playerWorldY(), x, y) <=
        preciseRadius:
      bot.intent = "precise approach to " & name
      bot.desiredMask = bot.preciseMaskForGoal(x, y)
    else:
      bot.desiredMask = bot.maskForWaypoint(bot.pathStep)
  bot.controllerMask = bot.desiredMask
  let mask = bot.applyJiggle(bot.controllerMask)
  let prefix =
    if bot.role == RoleImposter:
      "imposter "
    elif bot.isGhost:
      "ghost "
    else:
      "map lock "
  bot.thought(
    prefix & cameraLockName(bot.cameraLock) & " at camera (" &
    $bot.cameraX & ", " & $bot.cameraY & "), next " &
    movementName(mask)
  )
  mask

proc decideImposterMask(bot: var Bot): uint8 =
  ## Chooses imposter movement and kill behavior.
  bot.radarDots.setLen(0)
  if bot.radarTasks.len != bot.sim.tasks.len:
    bot.radarTasks = newSeq[bool](bot.sim.tasks.len)
  if bot.checkoutTasks.len != bot.sim.tasks.len:
    bot.checkoutTasks = newSeq[bool](bot.sim.tasks.len)
  for i in 0 ..< bot.radarTasks.len:
    bot.radarTasks[i] = false
  for i in 0 ..< bot.checkoutTasks.len:
    bot.checkoutTasks[i] = false
  bot.taskHoldTicks = 0
  bot.taskHoldIndex = -1
  let body = bot.nearestBody()
  if body.found:
    bot.imposterGoalIndex = bot.farthestFakeTargetIndexFrom(body.x, body.y)
    let fleeGoal = bot.fakeTargetGoalFor(bot.imposterGoalIndex)
    if fleeGoal.found:
      bot.goalIndex = fleeGoal.index
      return bot.navigateToPoint(
        fleeGoal.x,
        fleeGoal.y,
        "flee body to " & fleeGoal.name
      )
  let loneCrewmate = bot.loneVisibleCrewmate()
  if loneCrewmate.found and bot.imposterKillReady:
    let target = bot.visibleCrewmateWorld(loneCrewmate.crewmate)
    if bot.inKillRange(target.x, target.y):
      bot.imposterGoalIndex = bot.farthestFakeTargetIndex()
      bot.intent = "kill lone crewmate"
      bot.desiredMask = ButtonA
      bot.controllerMask = ButtonA
      bot.hasPathStep = false
      bot.path.setLen(0)
      bot.thought("lone crewmate in range, attacking")
      return ButtonA
    bot.goalIndex = -2
    return bot.navigateToPoint(
      target.x,
      target.y,
      "lone crewmate",
      KillApproachRadius
    )
  if bot.imposterGoalIndex < 0 or
      bot.imposterGoalIndex >= bot.fakeTargetCount():
    bot.imposterGoalIndex = bot.randomFakeTargetIndex()
  var goal = bot.fakeTargetGoalFor(bot.imposterGoalIndex)
  if not goal.found:
    bot.imposterGoalIndex = bot.randomFakeTargetIndex()
    goal = bot.fakeTargetGoalFor(bot.imposterGoalIndex)
  if not goal.found:
    bot.intent = "imposter idle, unreachable fake target"
    bot.thought("imposter idle, unreachable fake target")
    return 0
  if heuristic(bot.playerWorldX(), bot.playerWorldY(), goal.x, goal.y) <=
      TaskPreciseApproachRadius:
    bot.imposterGoalIndex = bot.randomFakeTargetIndex()
    goal = bot.fakeTargetGoalFor(bot.imposterGoalIndex)
    if not goal.found:
      bot.intent = "imposter idle, no next fake target"
      bot.thought("imposter idle, no next fake target")
      return 0
  bot.goalIndex = goal.index
  bot.navigateToPoint(goal.x, goal.y, "fake target " & goal.name)

proc decideNextMask(bot: var Bot): uint8 =
  ## Updates perception and chooses the next input mask.
  let centerStart = getMonoTime()
  bot.updateLocation()
  bot.centerMicros = int((getMonoTime() - centerStart).inMicroseconds)
  bot.astarMicros = 0
  if bot.interstitial:
    bot.updateMotionState()
    bot.hasGoal = false
    bot.hasPathStep = false
    bot.path.setLen(0)
    if bot.voting:
      return bot.decideVotingMask()
    bot.desiredMask = 0
    bot.controllerMask = 0
    bot.intent =
      if bot.interstitialText.len > 0:
        "interstitial: " & bot.interstitialText
      else:
        "interstitial screen mode"
    bot.thought(bot.intent)
    return 0
  bot.updateMotionState()
  bot.rememberVisibleMap()
  bot.updateTaskGuesses()
  bot.updateTaskIcons()
  bot.hasGoal = false
  bot.hasPathStep = false
  bot.path.setLen(0)
  bot.desiredMask = 0
  bot.controllerMask = 0
  bot.intent = "localizing"
  if not bot.localized:
    bot.thought("waiting for a reliable map lock")
    return 0
  bot.rememberHome()
  if bot.role == RoleImposter and not bot.isGhost:
    return bot.decideImposterMask()
  if not bot.isGhost:
    let body = bot.nearestBody()
    if body.found:
      bot.queueBodySeen(body.x, body.y)
      if bot.inReportRange(body.x, body.y) and
          abs(bot.velocityX) + abs(bot.velocityY) <= 1:
        return bot.reportBodyAction(body.x, body.y)
      return bot.navigateToPoint(
        body.x,
        body.y,
        "dead body",
        KillApproachRadius
      )
  if bot.taskHoldTicks > 0:
    return bot.holdTaskAction(
      if bot.goalName.len > 0:
        bot.goalName
      else:
        "task"
    )
  let goal = bot.nearestTaskGoal()
  if not goal.found:
    bot.intent = "localized, no task goal"
    bot.thought("localized near (" & $bot.playerWorldX() & ", " &
      $bot.playerWorldY() & ")")
    return 0
  bot.hasGoal = true
  bot.goalX = goal.x
  bot.goalY = goal.y
  bot.goalIndex = goal.index
  bot.goalName = goal.name
  if goal.state == TaskMandatory and
      bot.taskGoalReady(goal):
    bot.taskHoldTicks = bot.sim.config.taskCompleteTicks + TaskHoldPadding
    bot.taskHoldIndex = goal.index
    return bot.holdTaskAction(goal.name)
  if bot.isGhost:
    return bot.navigateToPoint(goal.x, goal.y, goal.name)
  let astarStart = getMonoTime()
  bot.path = bot.findPath(goal.x, goal.y)
  bot.astarMicros = int((getMonoTime() - astarStart).inMicroseconds)
  bot.pathStep = bot.choosePathStep()
  bot.hasPathStep = bot.pathStep.found
  bot.intent =
    if goal.index < 0:
      "gather at " & goal.name & " path=" & $bot.path.len
    else:
      "A* to " & goal.name & " path=" & $bot.path.len &
        " state=" & $goal.state
  if goal.state == TaskMandatory and
      heuristic(
        bot.playerWorldX(),
        bot.playerWorldY(),
        goal.x,
        goal.y
      ) <= TaskPreciseApproachRadius:
    bot.intent = "precise task approach to " & goal.name &
      " state=" & $goal.state
    bot.desiredMask = bot.preciseMaskForGoal(goal.x, goal.y)
  else:
    bot.desiredMask = bot.maskForWaypoint(bot.pathStep)
  bot.controllerMask = bot.desiredMask
  let mask = bot.applyJiggle(bot.controllerMask)
  bot.thought(
    "map lock " & cameraLockName(bot.cameraLock) & " at camera (" &
    $bot.cameraX & ", " & $bot.cameraY & "), next " &
    movementName(mask)
  )
  mask

proc stepUnpackedFrame*(bot: var Bot, frame: openArray[uint8]): uint8 =
  ## Steps the bot from one unpacked 4-bit framebuffer and returns an input mask.
  if frame.len != ScreenWidth * ScreenHeight:
    return 0
  if bot.unpacked.len != frame.len:
    bot.unpacked.setLen(frame.len)
  for i, value in frame:
    bot.unpacked[i] = value and 0x0f
  inc bot.frameTick
  result = bot.decideNextMask()
  bot.lastMask = result

proc stepPackedFrame*(bot: var Bot, frame: openArray[uint8]): uint8 =
  ## Steps the bot from one packed 4-bit framebuffer and returns an input mask.
  if frame.len != ProtocolBytes:
    return 0
  if bot.packed.len != frame.len:
    bot.packed.setLen(frame.len)
  for i, value in frame:
    bot.packed[i] = value
  unpack4bpp(bot.packed, bot.unpacked)
  inc bot.frameTick
  result = bot.decideNextMask()
  bot.lastMask = result

proc sheetSprite(sheet: Image, cellX, cellY: int): Sprite =
  ## Extracts one 12x12 sprite from the local sprite sheet.
  spriteFromImage(
    sheet.subImage(cellX * SpriteSize, cellY * SpriteSize, SpriteSize, SpriteSize)
  )

proc initBot(mapPath = ""): Bot =
  ## Builds a bot and loads all map and sprite data.
  setCurrentDir(gameDir())
  var config = defaultGameConfig()
  if mapPath.len > 0:
    config.mapPath = mapPath
  result.sim = initSimServer(config)
  let sheet = loadSpriteSheet()
  result.playerSprite = sheet.sheetSprite(0, 0)
  result.bodySprite = sheet.sheetSprite(1, 0)
  result.killButtonSprite = sheet.sheetSprite(3, 0)
  result.taskSprite = sheet.sheetSprite(4, 0)
  result.ghostSprite = sheet.sheetSprite(6, 0)
  result.ghostIconSprite = sheet.sheetSprite(7, 0)
  result.rng = initRand(getTime().toUnix() xor int64(getCurrentProcessId()))
  result.packed = newSeq[uint8](ProtocolBytes)
  result.unpacked = newSeq[uint8](ScreenWidth * ScreenHeight)
  result.mapTiles = newSeq[TileKnowledge](MapWidth * MapHeight)
  result.radarTasks = newSeq[bool](result.sim.tasks.len)
  result.checkoutTasks = newSeq[bool](result.sim.tasks.len)
  result.taskStates = newSeq[TaskState](result.sim.tasks.len)
  result.taskIconMisses = newSeq[int](result.sim.tasks.len)
  result.buildPatchEntries()
  result.cameraX = result.sim.buttonCameraX()
  result.cameraY = result.sim.buttonCameraY()
  result.lastCameraX = result.cameraX
  result.lastCameraY = result.cameraY
  result.taskHoldIndex = -1
  result.imposterGoalIndex = -1
  result.goalIndex = -1
  result.lastBodySeenX = low(int)
  result.lastBodySeenY = low(int)
  result.lastBodyReportX = low(int)
  result.lastBodyReportY = low(int)
  result.cameraLock = NoLock
  result.role = RoleCrewmate
  result.selfColorIndex = -1
  result.clearVotingState()
  result.intent = "waiting for first frame"

when defined(italkalotLibrary):
  const ITalkALotAbiVersion = 1
  const TrainableMasks = [
    0'u8,
    ButtonA,
    ButtonB,
    ButtonUp,
    ButtonUp or ButtonA,
    ButtonUp or ButtonB,
    ButtonDown,
    ButtonDown or ButtonA,
    ButtonDown or ButtonB,
    ButtonLeft,
    ButtonLeft or ButtonA,
    ButtonLeft or ButtonB,
    ButtonRight,
    ButtonRight or ButtonA,
    ButtonRight or ButtonB,
    ButtonUp or ButtonLeft,
    ButtonUp or ButtonLeft or ButtonA,
    ButtonUp or ButtonLeft or ButtonB,
    ButtonUp or ButtonRight,
    ButtonUp or ButtonRight or ButtonA,
    ButtonUp or ButtonRight or ButtonB,
    ButtonDown or ButtonLeft,
    ButtonDown or ButtonLeft or ButtonA,
    ButtonDown or ButtonLeft or ButtonB,
    ButtonDown or ButtonRight,
    ButtonDown or ButtonRight or ButtonA,
    ButtonDown or ButtonRight or ButtonB
  ]

  type ITalkALotPolicy = ref object
    bots: seq[Bot]

  var ITalkALotPolicies: seq[ITalkALotPolicy]

  proc italkalot_abi_version*(): cint {.exportc, dynlib.} =
    ## Returns the shared-library ABI version expected by Python wrappers.
    cint(ITalkALotAbiVersion)

  proc actionIndexForMask(mask: uint8): int32 =
    ## Maps a BitWorld button mask to the CoGames trainable action index.
    for i, value in TrainableMasks:
      if value == mask:
        return i.int32
    0'i32

  proc stepUnpackedFramePtr(
    bot: var Bot,
    frame: ptr UncheckedArray[uint8],
    frameLen: int
  ): uint8 =
    ## Steps the bot from one pointer-backed unpacked framebuffer.
    if frameLen != ScreenWidth * ScreenHeight:
      return 0
    if bot.unpacked.len != frameLen:
      bot.unpacked.setLen(frameLen)
    for i in 0 ..< frameLen:
      bot.unpacked[i] = frame[i] and 0x0f
    inc bot.frameTick
    result = bot.decideNextMask()
    bot.lastMask = result

  proc italkalot_new_policy*(numAgents: cint): cint {.exportc, dynlib.} =
    ## Creates a persistent Nim-backed ITalkALot policy and returns its handle.
    let count = max(1, int(numAgents))
    var policy = ITalkALotPolicy(bots: newSeq[Bot](count))
    for i in 0 ..< count:
      policy.bots[i] = initBot()
    ITalkALotPolicies.add(policy)
    cint(ITalkALotPolicies.len - 1)

  proc italkalot_step_batch*(
    handle: cint,
    agentIds: ptr UncheckedArray[int32],
    numAgentIds: cint,
    numAgents: cint,
    frameStack: cint,
    height: cint,
    width: cint,
    observations: pointer,
    actions: pointer
  ) {.exportc, dynlib.} =
    ## Steps a batch of unpacked pixel observations into CoGames action indices.
    if handle < 0 or int(handle) >= ITalkALotPolicies.len:
      return
    if observations.isNil or actions.isNil or agentIds.isNil:
      return
    if frameStack <= 0 or height != ScreenHeight or width != ScreenWidth:
      return

    let
      policy = ITalkALotPolicies[int(handle)]
      obs = cast[ptr UncheckedArray[uint8]](observations)
      outs = cast[ptr UncheckedArray[int32]](actions)
      frameLen = int(height) * int(width)
      rowStride = int(frameStack) * frameLen
      latestOffset = (int(frameStack) - 1) * frameLen

    if policy.bots.len < int(numAgents):
      let oldLen = policy.bots.len
      policy.bots.setLen(int(numAgents))
      for i in oldLen ..< policy.bots.len:
        policy.bots[i] = initBot()

    for row in 0 ..< int(numAgentIds):
      let agentId = int(agentIds[row])
      if agentId < 0 or agentId >= policy.bots.len:
        outs[row] = 0
        continue
      let frame = cast[ptr UncheckedArray[uint8]](
        cast[uint](obs) + uint(row * rowStride + latestOffset)
      )
      let mask = policy.bots[agentId].stepUnpackedFramePtr(frame, frameLen)
      outs[row] = actionIndexForMask(mask)

when not defined(italkalotLibrary) and not defined(botHeadless):
  proc drawOutline(sk: Silky, pos, size: Vec2, color: ColorRGBX, thickness = 1.0) =
    ## Draws an unfilled rectangle.
    sk.drawRect(pos, vec2(size.x, thickness), color)
    sk.drawRect(vec2(pos.x, pos.y + size.y - thickness), vec2(size.x, thickness), color)
    sk.drawRect(pos, vec2(thickness, size.y), color)
    sk.drawRect(vec2(pos.x + size.x - thickness, pos.y), vec2(thickness, size.y), color)

  proc drawLine(sk: Silky, a, b: Vec2, color: ColorRGBX) =
    ## Draws a simple pixel-like line.
    let
      dx = b.x - a.x
      dy = b.y - a.y
      steps = max(1, int(max(abs(dx), abs(dy)) / 4.0'f))
    for i in 0 .. steps:
      let t = i.float32 / steps.float32
      sk.drawRect(
        vec2(a.x + dx * t - 1.0'f, a.y + dy * t - 1.0'f),
        vec2(3, 3),
        color
      )

  proc taskStateColor(state: TaskState): ColorRGBX =
    ## Returns a map marker color for a task state.
    case state
    of TaskNotDoing:
      ViewerTask
    of TaskMaybe:
      ViewerTaskGuess
    of TaskMandatory:
      ViewerButton
    of TaskCompleted:
      ViewerMutedText

  proc crewmateOutlineColor(bot: Bot, colorIndex: int): ColorRGBX =
    ## Returns the debug outline color for one visible crewmate.
    if bot.knownImposterColor(colorIndex):
      ViewerImp
    else:
      ViewerCrew

  proc drawCrewmateFrameOutlines(
    sk: Silky,
    bot: Bot,
    x,
    y,
    scale: float32
  ) =
    ## Draws visible crewmate team outlines in screen space.
    for crewmate in bot.visibleCrewmates:
      sk.drawOutline(
        vec2(
          x + crewmate.x.float32 * scale,
          y + crewmate.y.float32 * scale
        ),
        vec2(
          bot.playerSprite.width.float32 * scale,
          bot.playerSprite.height.float32 * scale
        ),
        bot.crewmateOutlineColor(crewmate.colorIndex),
        2
      )

  proc drawCrewmateMapOutlines(
    sk: Silky,
    bot: Bot,
    x,
    y,
    scale: float32
  ) =
    ## Draws visible crewmate team outlines in map space.
    if not bot.localized:
      return
    for crewmate in bot.visibleCrewmates:
      let
        world = bot.visibleCrewmateWorld(crewmate)
        spriteX = world.x - SpriteDrawOffX
        spriteY = world.y - SpriteDrawOffY
      sk.drawOutline(
        vec2(x + spriteX.float32 * scale, y + spriteY.float32 * scale),
        vec2(
          bot.playerSprite.width.float32 * scale,
          bot.playerSprite.height.float32 * scale
        ),
        bot.crewmateOutlineColor(crewmate.colorIndex),
        2
      )

  proc drawFrameView(sk: Silky, bot: Bot, x, y: float32) =
    ## Draws the latest 128x128 game frame.
    let pixelScale = ViewerFrameScale
    sk.drawRect(
      vec2(x, y),
      vec2(ScreenWidth.float32 * pixelScale, ScreenHeight.float32 * pixelScale),
      ViewerPanelAlt
    )
    for py in 0 ..< ScreenHeight:
      for px in 0 ..< ScreenWidth:
        let index = bot.unpacked[py * ScreenWidth + px]
        sk.drawRect(
          vec2(x + px.float32 * pixelScale, y + py.float32 * pixelScale),
          vec2(pixelScale, pixelScale),
          sampleColor(index)
        )
    sk.drawCrewmateFrameOutlines(bot, x, y, pixelScale)
    if bot.interstitial:
      return
    let
      button = bot.sim.gameMap.button
      buttonX = button.x - bot.cameraX
      buttonY = button.y - bot.cameraY
    if buttonX + button.w >= 0 and buttonY + button.h >= 0 and
        buttonX < ScreenWidth and buttonY < ScreenHeight:
      sk.drawOutline(
        vec2(x + buttonX.float32 * pixelScale, y + buttonY.float32 * pixelScale),
        vec2(button.w.float32 * pixelScale, button.h.float32 * pixelScale),
        ViewerButton,
        2
      )
    sk.drawRect(
      vec2(
        x + PlayerScreenX.float32 * pixelScale - 3,
        y + PlayerScreenY.float32 * pixelScale - 3
      ),
      vec2(7, 7),
      ViewerPlayer
    )
    let playerPos = vec2(
      x + PlayerScreenX.float32 * pixelScale,
      y + PlayerScreenY.float32 * pixelScale
    )
    for dot in bot.radarDots:
      let dotPos = vec2(
        x + dot.x.float32 * pixelScale + pixelScale * 0.5,
        y + dot.y.float32 * pixelScale + pixelScale * 0.5
      )
      sk.drawLine(playerPos, dotPos, ViewerRadarLine)
      sk.drawRect(dotPos - vec2(4, 4), vec2(9, 9), ViewerTaskGuess)
    for task in bot.sim.tasks:
      let
        taskX = task.x - bot.cameraX
        taskY = task.y - bot.cameraY
        taskVisible = taskX + task.w >= 0 and taskY + task.h >= 0 and
          taskX < ScreenWidth and taskY < ScreenHeight
      if not taskVisible:
        continue
      let
        icon = bot.taskIconInspectRect(task)
        hasIcon = bot.taskIconVisibleFor(task)
        color =
          if hasIcon:
            ViewerPlayer
          else:
            ViewerTask
        taskPos = vec2(
          x + taskX.float32 * pixelScale,
          y + taskY.float32 * pixelScale
        )
        taskSize = vec2(
          task.w.float32 * pixelScale,
          task.h.float32 * pixelScale
        )
      sk.drawOutline(taskPos, taskSize, color, 2)
      if icon.x + icon.w >= 0 and icon.y + icon.h >= 0 and
          icon.x < ScreenWidth and icon.y < ScreenHeight:
        let
          iconPos = vec2(
            x + icon.x.float32 * pixelScale,
            y + icon.y.float32 * pixelScale
          )
          iconSize = vec2(
            icon.w.float32 * pixelScale,
            icon.h.float32 * pixelScale
          )
        sk.drawOutline(iconPos, iconSize, color, 2)
        sk.drawLine(
          taskPos + taskSize * 0.5,
          iconPos + iconSize * 0.5,
          color
        )
    for icon in bot.visibleTaskIcons:
      sk.drawOutline(
        vec2(
          x + icon.x.float32 * pixelScale,
          y + icon.y.float32 * pixelScale
        ),
        vec2(
          bot.taskSprite.width.float32 * pixelScale,
          bot.taskSprite.height.float32 * pixelScale
        ),
        ViewerButton,
        2
      )

  proc drawMapView(sk: Silky, bot: Bot, x, y: float32) =
    ## Draws the map, inferred viewport, and known task stations.
    let scale = ViewerMapScale
    sk.drawRect(
      vec2(x, y),
      vec2(MapWidth.float32 * scale, MapHeight.float32 * scale),
      ViewerUnknown
    )
    for my in countup(0, MapHeight - 1, 2):
      for mx in countup(0, MapWidth - 1, 2):
        let idx = mapIndexSafe(mx, my)
        let color =
          if bot.sim.wallMask[idx]:
            ViewerWall
          elif bot.sim.walkMask[idx]:
            ViewerWalk
          else:
            sampleColor(bot.sim.mapPixels[idx])
        sk.drawRect(
          vec2(x + mx.float32 * scale, y + my.float32 * scale),
          vec2(max(1.0'f, scale * 2), max(1.0'f, scale * 2)),
          color
        )
    if bot.interstitial:
      return
    for i in 0 ..< bot.sim.tasks.len:
      let
        task = bot.sim.tasks[i]
        center = task.taskCenter()
        state =
          if bot.taskStates.len == bot.sim.tasks.len:
            bot.taskStates[i]
          else:
            TaskNotDoing
      sk.drawRect(
        vec2(x + center.x.float32 * scale - 3, y + center.y.float32 * scale - 3),
        vec2(7, 7),
        taskStateColor(state)
      )
    if bot.taskStates.len == bot.sim.tasks.len:
      for i in 0 ..< bot.sim.tasks.len:
        let
          isRadarTask =
            bot.radarTasks.len == bot.sim.tasks.len and bot.radarTasks[i]
          isCheckoutTask =
            bot.checkoutTasks.len == bot.sim.tasks.len and bot.checkoutTasks[i]
        if bot.taskStates[i] != TaskMandatory and
            not isRadarTask and
            not isCheckoutTask:
          continue
        let
          center = bot.sim.tasks[i].taskCenter()
          color =
            if bot.taskStates[i] == TaskMandatory:
              taskStateColor(TaskMandatory)
            else:
              taskStateColor(TaskMaybe)
          pos = vec2(
            x + center.x.float32 * scale - 5,
            y + center.y.float32 * scale - 5
          )
        sk.drawOutline(pos, vec2(11, 11), color, 2)
        if bot.localized:
          sk.drawLine(
            vec2(
              x + bot.playerWorldX().float32 * scale,
              y + bot.playerWorldY().float32 * scale
            ),
            pos + vec2(5, 5),
            ViewerRadarLine
          )
    let button = bot.sim.gameMap.button
    sk.drawOutline(
      vec2(
        x + button.x.float32 * scale,
        y + button.y.float32 * scale
      ),
      vec2(button.w.float32 * scale, button.h.float32 * scale),
      ViewerButton,
      1
    )
    if bot.localized:
      sk.drawOutline(
        vec2(x + bot.cameraX.float32 * scale, y + bot.cameraY.float32 * scale),
        vec2(ScreenWidth.float32 * scale, ScreenHeight.float32 * scale),
        ViewerViewport,
        1
      )
      sk.drawRect(
        vec2(
          x + bot.playerWorldX().float32 * scale - 2,
          y + bot.playerWorldY().float32 * scale - 2
        ),
        vec2(5, 5),
        ViewerPlayer
      )
      sk.drawCrewmateMapOutlines(bot, x, y, scale)
    if bot.homeSet:
      sk.drawOutline(
        vec2(x + bot.homeX.float32 * scale - 5, y + bot.homeY.float32 * scale - 5),
        vec2(10, 10),
        ViewerButton,
        1
      )
    if bot.hasGoal:
      sk.drawRect(
        vec2(x + bot.goalX.float32 * scale - 4, y + bot.goalY.float32 * scale - 4),
        vec2(9, 9),
        ViewerTask
      )
    if bot.path.len > 0:
      var previous = vec2(
        x + bot.playerWorldX().float32 * scale,
        y + bot.playerWorldY().float32 * scale
      )
      for i in countup(0, bot.path.high, 8):
        let current = vec2(
          x + bot.path[i].x.float32 * scale,
          y + bot.path[i].y.float32 * scale
        )
        sk.drawLine(previous, current, ViewerPath)
        previous = current
      if bot.hasGoal:
        sk.drawLine(
          previous,
          vec2(x + bot.goalX.float32 * scale, y + bot.goalY.float32 * scale),
          ViewerPath
        )
    if bot.hasPathStep:
      sk.drawRect(
        vec2(
          x + bot.pathStep.x.float32 * scale - 2,
          y + bot.pathStep.y.float32 * scale - 2
        ),
        vec2(5, 5),
        ViewerButton
      )

  proc initViewerApp(): ViewerApp =
    ## Opens the diagnostic viewer window.
    result = ViewerApp()
    result.window = newWindow(
      title = "Among Them Bot Viewer",
      size = ivec2(ViewerWindowWidth, ViewerWindowHeight),
      style = Decorated,
      visible = true
    )
    makeContextCurrent(result.window)
    when not defined(useDirectX):
      loadExtensions()
    result.silky = newSilky(result.window, atlasPath())

  proc pumpViewer(
    viewer: ViewerApp,
    bot: Bot,
    connected: bool,
    url: string
  ) =
    ## Pumps and renders one viewer frame.
    if viewer.isNil:
      return
    pollEvents()
    if viewer.window.buttonPressed[KeyEscape]:
      viewer.window.closeRequested = true
    if viewer.window.closeRequested:
      return
    let
      frameSize = viewer.window.size
      framePos = vec2(ViewerMargin, ViewerMargin + 28)
      mapPos = vec2(
        framePos.x + ScreenWidth.float32 * ViewerFrameScale + 24,
        ViewerMargin + 28
      )
      mapSize = vec2(MapWidth.float32 * ViewerMapScale, MapHeight.float32 * ViewerMapScale)
      infoPos = vec2(ViewerMargin, framePos.y + ScreenHeight.float32 * ViewerFrameScale + 28)
      infoSize = vec2(frameSize.x.float32 - ViewerMargin * 2, 300)
      sk = viewer.silky
    sk.beginUI(viewer.window, frameSize)
    sk.clearScreen(ViewerBackground)
    discard sk.drawText("Default", "Among Them Bot Viewer", vec2(ViewerMargin, ViewerMargin), ViewerText)
    discard sk.drawText("Default", "Live frame", vec2(framePos.x, framePos.y - 18), ViewerMutedText)
    discard sk.drawText("Default", "Map lock", vec2(mapPos.x, mapPos.y - 18), ViewerMutedText)
    sk.drawRect(
      framePos - vec2(8, 8),
      vec2(ScreenWidth.float32 * ViewerFrameScale + 16, ScreenHeight.float32 * ViewerFrameScale + 16),
      ViewerPanel
    )
    sk.drawRect(mapPos - vec2(8, 8), mapSize + vec2(16, 16), ViewerPanel)
    sk.drawRect(infoPos - vec2(8, 8), infoSize + vec2(16, 16), ViewerPanel)
    sk.drawFrameView(bot, framePos.x, framePos.y)
    sk.drawMapView(bot, mapPos.x, mapPos.y)
    let goalText =
      if bot.hasGoal:
        let ready =
          bot.goalIndex >= 0 and
          bot.goalIndex < bot.sim.tasks.len and
          bot.taskReadyAtGoal(bot.goalIndex, bot.goalX, bot.goalY)
        "goal: " & bot.goalName &
          " dist=" & $heuristic(
            bot.playerWorldX(),
            bot.playerWorldY(),
            bot.goalX,
            bot.goalY
          ) &
          " ready=" & $ready & "\n"
      else:
        "goal: none\n"
    let infoText =
      "intent: " & bot.intent & "\n" &
      "room: " & bot.roomName() & "\n" &
      "timing sprite scans: " & $bot.spriteScanMicros & "us (" &
        $(bot.spriteScanMicros div 1000) & "ms)\n" &
      "timing localize local: " & $bot.localizeLocalMicros & "us (" &
        $(bot.localizeLocalMicros div 1000) & "ms)\n" &
      "timing localize patch: " & $bot.localizePatchMicros & "us (" &
        $(bot.localizePatchMicros div 1000) & "ms)\n" &
      "timing localize spiral: " & $bot.localizeSpiralMicros & "us (" &
        $(bot.localizeSpiralMicros div 1000) & "ms)\n" &
      "timing pathing: " & $bot.astarMicros & "us (" &
        $(bot.astarMicros div 1000) & "ms)\n" &
      "client tick: " & $bot.frameTick & "\n" &
      "BUTTONS HELD: " & inputMaskSummary(bot.lastMask) & "\n" &
      "timing center: " & $bot.centerMicros & "us (" &
        $(bot.centerMicros div 1000) & "ms)\n" &
      "frames buffered: " & $bot.frameBufferLen &
        " dropped=" & $bot.framesDropped &
        " total=" & $bot.skippedFrames & "\n" &
      "interstitial text: " &
        (if bot.interstitialText.len > 0: bot.interstitialText else: "none") &
        "\n" &
      "lock: " & cameraLockName(bot.cameraLock) & " score=" & $bot.cameraScore & "\n" &
      "role: " & roleName(bot.role) &
        " self=" & playerColorName(bot.selfColorIndex) &
        " ghost=" & $bot.isGhost &
        " ghost icon frames=" & $bot.ghostIconFrames &
        " kill ready=" & $bot.imposterKillReady &
        " imp goal=" & $bot.imposterGoalIndex & "\n" &
      "known imps: " & bot.knownImposterSummary() & "\n" &
      "voting: " & $bot.voting &
        " count=" & $bot.votePlayerCount &
        " listen=" & $max(0, bot.frameTick - bot.voteStartTick) &
        " cursor=" & bot.voteTargetName(bot.voteCursor) &
        " target=" & bot.voteTargetName(bot.voteTarget) & "\n" &
      "votes: " & bot.voteSummary() & "\n" &
      "vote chat sus: " & playerColorName(bot.voteChatSusColor) &
        " text=" & bot.voteChatText & "\n" &
      "camera: (" & $bot.cameraX & ", " & $bot.cameraY & ")\n" &
      "player: (" & $bot.playerWorldX() & ", " & $bot.playerWorldY() & ")\n" &
      "home: " & (
        if bot.homeSet:
          "(" & $bot.homeX & ", " & $bot.homeY & ")"
        else:
          "unset"
      ) & " started=" & $bot.gameStarted & "\n" &
      "velocity: (" & $bot.velocityX & ", " & $bot.velocityY & ")\n" &
      "crewmates masked: " & $bot.visibleCrewmates.len &
        " bodies=" & $bot.visibleBodies.len &
        " ghosts=" & $bot.visibleGhosts.len & "\n" &
      "suspect: " & bot.suspectSummary() & "\n" &
      "radar dots: " & $bot.radarDots.len &
        " radar tasks=" & $bot.radarTaskCount() &
        " checkout=" & $bot.checkoutTaskCount() &
        " task icons=" & $bot.visibleTaskIcons.len & "\n" &
      "tasks mandatory=" & $bot.taskStateCount(TaskMandatory) &
        " completed=" & $bot.taskStateCount(TaskCompleted) & "\n" &
      goalText &
      "path pixels: " & $bot.path.len & "\n" &
      "desired: " & inputMaskSummary(bot.desiredMask) & "\n" &
      "controller: " & inputMaskSummary(bot.controllerMask) & "\n" &
      "stuck: " & $bot.stuckFrames & " jiggle=" & $bot.jiggleTicks & "\n" &
      "last thought: " & (
        if bot.lastThought.len > 0:
          bot.lastThought
        else:
          "waiting"
      ) & "\n" &
      "status: " & (if connected: "connected" else: "reconnecting") & "\n" &
      "url: " & url
    discard sk.drawText("Default", infoText, infoPos, ViewerText, infoSize.x, infoSize.y)
    sk.endUi()
    viewer.window.swapBuffers()

  proc viewerOpen(viewer: ViewerApp): bool =
    ## Returns true when the diagnostic viewer should keep running.
    viewer.isNil or not viewer.window.closeRequested

when not defined(italkalotLibrary) and defined(botHeadless):
  proc initViewerApp(): ViewerApp =
    ## Returns no viewer for headless builds.
    nil

  proc pumpViewer(
    viewer: ViewerApp,
    bot: Bot,
    connected: bool,
    url: string
  ) =
    ## Ignores viewer frames in headless builds.
    discard

  proc viewerOpen(viewer: ViewerApp): bool =
    ## Returns true because headless builds have no viewer window.
    true

when not defined(italkalotLibrary):
  proc queryEscape(value: string): string =
    ## Escapes a small string for use in a websocket query parameter.
    const Hex = "0123456789ABCDEF"
    for ch in value:
      if ch in {'a' .. 'z'} or ch in {'A' .. 'Z'} or ch in {'0' .. '9'} or
          ch in {'-', '_', '.', '~'}:
        result.add(ch)
      else:
        let byte = ord(ch)
        result.add('%')
        result.add(Hex[(byte shr 4) and 0x0f])
        result.add(Hex[byte and 0x0f])

  proc addQueryParam(url, key, value: string): string =
    ## Adds one encoded query parameter to a URL.
    if value.len == 0:
      return url
    url & (if '?' in url: "&" else: "?") &
      key & "=" & value.queryEscape()

  proc playerConnectUrl(
    endpoint,
    name,
    token: string,
    slot: int
  ): string =
    ## Adds player join query parameters to an endpoint.
    result = endpoint
    result = result.addQueryParam("name", name)
    if slot >= 0:
      result = result.addQueryParam("slot", $slot)
    result = result.addQueryParam("token", token)

  proc acceptPlayerMessage(
    ws: WebSocket,
    message: Message,
    queuedFrames: var seq[string]
  ) =
    ## Handles one websocket message while filling the local frame queue.
    case message.kind
    of BinaryMessage:
      if message.data.len == ProtocolBytes:
        queuedFrames.add(message.data)
    of Ping:
      ws.send(message.data, Pong)
    of TextMessage, Pong:
      discard

  proc receiveLatestFrame(ws: WebSocket, bot: var Bot, gui: bool): bool =
    ## Receives frames and only drops them under high backlog.
    if bot.queuedFrames.len == 0:
      let firstMessage = ws.receiveMessage(if gui: 10 else: -1)
      if firstMessage.isNone:
        bot.frameBufferLen = 0
        bot.framesDropped = 0
        return false
      ws.acceptPlayerMessage(firstMessage.get, bot.queuedFrames)

    var drained = 0
    while drained < MaxFrameDrain:
      let message = ws.receiveMessage(0)
      if message.isNone:
        break
      ws.acceptPlayerMessage(message.get, bot.queuedFrames)
      inc drained

    if bot.queuedFrames.len == 0:
      bot.frameBufferLen = 0
      bot.framesDropped = 0
      return false

    var
      frame = ""
      frameAdvance = 1
    bot.framesDropped = 0
    if bot.queuedFrames.len >= FrameDropThreshold:
      bot.framesDropped = bot.queuedFrames.len - 1
      frameAdvance = bot.queuedFrames.len
      frame = bot.queuedFrames[^1]
      bot.queuedFrames.setLen(0)
    else:
      frame = bot.queuedFrames[0]
      bot.queuedFrames.delete(0)

    bot.frameBufferLen = bot.queuedFrames.len
    bot.skippedFrames += bot.framesDropped
    if bot.framesDropped > 0:
      echo "frames dropped: ", bot.framesDropped,
        " buffered=", frameAdvance,
        " total=", bot.skippedFrames,
        " tick=", bot.frameTick + frameAdvance
    bot.frameTick += frameAdvance
    blobToBytes(frame, bot.packed)
    unpack4bpp(bot.packed, bot.unpacked)
    true

  proc ensureWsPath(url: string, defaultPath: string): string =
    ## Inserts `defaultPath` if the URL has no path beyond the authority,
    ## so `--url:ws://host:port` still hits the WebSocket endpoint.
    let s = url.find("://")
    let start = if s < 0: 0 else: s + 3
    for i in start ..< url.len:
      case url[i]
      of '/': return url
      of '?', '#': return url[0 ..< i] & defaultPath & url[i .. ^1]
      else: discard
    url & defaultPath

  proc runBot(
    host = DefaultHost,
    port = PlayerDefaultPort,
    gui = false,
    name = "",
    mapPath = "",
    url = "",
    token = "",
    slot = -1,
    exitOnDisconnect = false
  ) =
    ## Connects to an Among Them server and processes player frames.
    ## If `url` is non-empty it is used as the WebSocket endpoint (scheme,
    ## host, port, path); otherwise we build ws://host:port/player. A
    ## missing path is filled in with WebSocketPath.
    var bot = initBot(mapPath)
    let endpoint =
      if url.len > 0: ensureWsPath(url, WebSocketPath)
      else: "ws://" & host & ":" & $port & WebSocketPath
    let connectUrl = playerConnectUrl(endpoint, name, token, slot)
    var
      viewer =
        if gui: initViewerApp()
        else: nil
      connected = false
      notifiedFailure = false
    while viewer.viewerOpen():
      try:
        let ws = newWebSocket(connectUrl)
        echo "connected to ", connectUrl
        notifiedFailure = false
        var lastMask = 0xff'u8
        bot.queuedFrames.setLen(0)
        bot.frameBufferLen = 0
        bot.framesDropped = 0
        connected = true
        while viewer.viewerOpen():
          if gui:
            viewer.pumpViewer(bot, connected, connectUrl)
            if not viewer.viewerOpen():
              ws.close()
              break
          if not ws.receiveLatestFrame(bot, gui):
            continue
          let nextMask = bot.decideNextMask()
          bot.lastMask = nextMask
          if nextMask != lastMask:
            ws.send(blobFromMask(nextMask), BinaryMessage)
            lastMask = nextMask
          if bot.interstitial and
              bot.pendingChat.len > 0 and
              not bot.interstitialText.isGameOverText():
            ws.send(blobFromChat(bot.pendingChat), BinaryMessage)
            bot.pendingChat = ""
      except Exception as e:
        if connected:
          echo "connection lost: ", e.msg
          if exitOnDisconnect:
            break
        elif not notifiedFailure:
          echo "connection failed: ", e.msg
          notifiedFailure = true
        connected = false
        if gui:
          let reconnectStart = getMonoTime()
          while viewer.viewerOpen() and
              (getMonoTime() - reconnectStart).inMilliseconds < 250:
            viewer.pumpViewer(bot, connected, connectUrl)
            sleep(10)
        else:
          sleep(250)

when isMainModule and not defined(italkalotLibrary):
  var
    address = DefaultHost
    port = PlayerDefaultPort
    gui = false
    name = ""
    mapPath = ""
    url = getEnv("COWORLD_PLAYER_WS_URL")
    token = ""
    slot = -1
    exitOnDisconnect = url.len > 0
  for kind, key, val in getopt():
    case kind
    of cmdLongOption:
      case key
      of "address":
        address = val
      of "port":
        port = parseInt(val)
      of "gui":
        gui = true
      of "name":
        name = val
      of "token":
        token = val
      of "slot":
        slot = parseInt(val)
      of "map":
        mapPath = val
      of "url":
        url = val
      else:
        discard
    else:
      discard
  if mapPath.len > 0 and not mapPath.isAbsolute():
    mapPath = absolutePath(mapPath)
  let target =
    if url.len > 0: url
    else: "ws://" & address & ":" & $port
  echo "starting amongthemstarter -> ", target
  runBot(address, port, gui, name, mapPath, url, token, slot, exitOnDisconnect)
