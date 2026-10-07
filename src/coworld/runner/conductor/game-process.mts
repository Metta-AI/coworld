import { spawn, type ChildProcessByStdio } from 'node:child_process'
import type { Readable } from 'node:stream'

const maximumDiagnosticBytes = 64 * 1024
const shutdownGracePeriodMs = 1000

type GameProcessOptions = {
  executable: string
  arguments_: string[]
  environment: Record<string, string>
  scratchDirectory: string
}

type GameProcessStatus = 'running' | 'launch_failed' | 'process_failed' | 'exited'

export class GameProcess {
  private readonly childProcess: ChildProcessByStdio<null, Readable, Readable>
  private readonly closed: Promise<void>
  private hasClosed = false
  private launchFailed = false
  private diagnosticBytes: Buffer = Buffer.alloc(0)

  constructor({ executable, arguments_, environment, scratchDirectory }: GameProcessOptions) {
    this.childProcess = spawn(executable, arguments_, {
      stdio: ['ignore', 'pipe', 'pipe'],
      cwd: scratchDirectory,
      env: {
        PATH: '/usr/local/bin:/usr/bin:/bin',
        HOME: scratchDirectory,
        TMPDIR: scratchDirectory,
        COGAME_HOST: '127.0.0.1',
        COGAME_PORT: '8081',
        ...environment,
      },
    })

    for (const stream of [this.childProcess.stdout, this.childProcess.stderr]) {
      stream.on('data', (chunk: Buffer) => {
        const combinedDiagnostics = Buffer.concat([this.diagnosticBytes, chunk])
        this.diagnosticBytes = combinedDiagnostics.subarray(-maximumDiagnosticBytes)
      })
    }

    this.closed = new Promise((resolve) => {
      this.childProcess.once('error', (error) => {
        this.launchFailed = true
        this.hasClosed = true
        this.diagnosticBytes = Buffer.from(String(error)).subarray(-maximumDiagnosticBytes)
        resolve()
      })

      this.childProcess.once('close', () => {
        this.hasClosed = true
        resolve()
      })
    })
  }

  get status(): GameProcessStatus {
    if (this.launchFailed) {
      return 'launch_failed'
    }

    const { exitCode, signalCode } = this.childProcess
    const exitedWithError = exitCode !== null && exitCode !== 0

    if (exitedWithError || signalCode !== null) {
      return 'process_failed'
    }

    return this.hasClosed ? 'exited' : 'running'
  }

  get diagnostics(): Buffer {
    return this.diagnosticBytes
  }

  async stop(): Promise<void> {
    if (this.hasClosed) {
      return
    }

    this.childProcess.kill('SIGTERM')

    let shutdownTimer: NodeJS.Timeout | undefined
    const gracePeriodExpired = new Promise<void>((resolve) => {
      shutdownTimer = setTimeout(resolve, shutdownGracePeriodMs)
      shutdownTimer.unref()
    })

    try {
      await Promise.race([this.closed, gracePeriodExpired])

      if (!this.hasClosed) {
        this.childProcess.kill('SIGKILL')
        await this.closed
      }
    } finally {
      clearTimeout(shutdownTimer)
    }
  }
}
