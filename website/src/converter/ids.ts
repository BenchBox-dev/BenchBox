import { docutilsMakeId } from "../lib/docutils-slug.ts";

export class IdAllocator {
  private readonly used = new Set<string>();
  private counter = 0;

  all(): string[] {
    return [...this.used].sort();
  }

  fromName(name: string): string {
    const base = docutilsMakeId(name);
    if (base && !this.used.has(base)) {
      this.used.add(base);
      return base;
    }
    return this.automatic();
  }

  automatic(): string {
    let id: string;
    do {
      this.counter += 1;
      id = `id${this.counter}`;
    } while (this.used.has(id));
    this.used.add(id);
    return id;
  }
}
