export class ConverterError extends Error {
  readonly file: string;
  readonly line: number;

  constructor(file: string, line: number, message: string) {
    super(`${file}:${line}: ${message}`);
    this.name = new.target.name;
    this.file = file;
    this.line = line;
  }
}

export class UnknownConstructError extends ConverterError {
  readonly construct: string;

  constructor(file: string, line: number, construct: string, detail = `unknown construct ${construct}`) {
    super(file, line, detail);
    this.construct = construct;
  }
}

export class NotYetImplementedError extends UnknownConstructError {
  readonly owner: string;

  constructor(file: string, line: number, construct: string, owner: string) {
    super(file, line, construct, `${construct} is not yet implemented (handler slot: ${owner})`);
    this.owner = owner;
  }
}

export class UnresolvedReferenceError extends ConverterError {
  readonly reference: string;

  constructor(file: string, line: number, reference: string, detail: string) {
    super(file, line, `${reference} ${detail}`);
    this.reference = reference;
  }
}

export class ConversionFailedError extends Error {
  readonly errors: readonly ConverterError[];

  constructor(errors: readonly ConverterError[]) {
    super(`conversion failed with ${errors.length} error${errors.length === 1 ? "" : "s"}`);
    this.name = "ConversionFailedError";
    this.errors = errors;
  }
}

export function constructOf(error: ConverterError): string {
  return error instanceof UnknownConstructError ? error.construct : error instanceof UnresolvedReferenceError ? `unresolved:${error.reference.split(":")[0]}` : error.name;
}
