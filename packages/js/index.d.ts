import type { Writable, Readable } from 'node:stream';

/** Encode a whole value to UTF-8 JSON bytes. */
export function encode(value: unknown): Buffer;

/** Decode UTF-8 JSON bytes (or a string) to a value. */
export function decode(data: Buffer | string): unknown;

/** Stream a value to a writable. */
export function encodeTo(value: unknown, writable: Writable): Promise<void>;

/** Read a whole value from a readable. */
export function decodeFrom(readable: Readable): Promise<unknown>;

/**
 * Stream a large collection as a JSON array, one element at a time. Peak memory
 * is bounded by the largest single element, not the length of the collection.
 * Returns the number of elements written.
 */
export function encodeArray(
  items: Iterable<unknown> | AsyncIterable<unknown>,
  writable: Writable
): Promise<number>;

/**
 * Lazily parse a top-level JSON array from a readable, yielding one element at a
 * time so memory stays proportional to the largest element.
 */
export function decodeArray(readable: Readable): AsyncGenerator<unknown>;
