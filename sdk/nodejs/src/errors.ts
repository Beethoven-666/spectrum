/**
 * Exception hierarchy for the H1 SDK.
 *
 * The hierarchy mirrors the C++ and Python SDKs (see docs/PROTOCOL.md §6).
 */

/** Base class for every error raised by the SDK. */
export class H1Error extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'H1Error';
    // Restore prototype chain in case of downlevel-targeted transpilation.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Raised when a frame is malformed (header, footer, length or checksum bad). */
export class ProtocolError extends H1Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProtocolError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Raised when a serial read does not complete inside the configured timeout. */
export class TimeoutError extends H1Error {
  constructor(message: string) {
    super(message);
    this.name = 'TimeoutError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Raised when the device returns a non-success status byte (0x15 or 0xFF). */
export class DeviceError extends H1Error {
  /** Device status byte (0x15 = invalid command, 0xFF = unsupported / out of range). */
  readonly code: number;
  /** Command type that triggered the error, if known. */
  readonly cmdType: number | undefined;

  constructor(code: number, message: string, cmdType?: number) {
    super(message);
    this.name = 'DeviceError';
    this.code = code;
    this.cmdType = cmdType;
    Object.setPrototypeOf(this, new.target.prototype);
  }

  override toString(): string {
    const cmd =
      this.cmdType !== undefined
        ? ` (cmd=0x${this.cmdType.toString(16).padStart(2, '0').toUpperCase()})`
        : '';
    const code = this.code.toString(16).padStart(2, '0').toUpperCase();
    return `${this.name}: ${this.message} [code=0x${code}${cmd}]`;
  }
}
