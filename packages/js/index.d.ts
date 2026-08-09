import type { Writable, Readable } from 'node:stream';

/** Encode a whole value to UTF-8 JSON bytes. */
export function encode(value: unknown): Buffer;

/** Decode UTF-8 JSON bytes (or a string) to a value. */
export function decode(data: Buffer | string): unknown;

/** Stream a value to a writable. */
export function encodeTo(value: unknown, writable: Writable): Promise<void>;

/** Read a whole value from a readable. */
export function decodeFrom(readable: Readable): Promise<unknown>;

/** Options for the streaming array helpers. */
export interface ArrayOptions {
  /** Wire format: "json" (default), "xml", or "msgpack" (binary). */
  format?: 'json' | 'xml' | 'msgpack';
  /** XML only: the wrapper element name (default "items"). */
  root?: string;
  /** XML only: the per-element tag name (default "item"). */
  item?: string;
  /** JSON only: max nesting depth before the decoder rejects input (default 200; 0 disables). */
  maxDepth?: number;
}

/**
 * Stream a large collection element-by-element. Peak memory is bounded by the
 * largest single element, not the length of the collection. `options.format`
 * selects "json" (default) or "xml". Returns the number of elements written.
 */
export function encodeArray(
  items: Iterable<unknown> | AsyncIterable<unknown>,
  writable: Writable,
  options?: ArrayOptions
): Promise<number>;

/**
 * Lazily parse a streamed collection from a readable, yielding one element at a
 * time so memory stays proportional to the largest element. `options.format`
 * selects "json" (default) or "xml".
 */
export function decodeArray(readable: Readable, options?: ArrayOptions): AsyncGenerator<unknown>;
