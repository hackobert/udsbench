/** Kleiner typisierter Event-Emitter. */
export class Emitter<T> {
  private listeners = new Set<(value: T) => void>();

  on(fn: (value: T) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit(value: T): void {
    for (const fn of [...this.listeners]) {
      try {
        fn(value);
      } catch (exc) {
        console.error(exc);
      }
    }
  }

  get size(): number {
    return this.listeners.size;
  }
}
