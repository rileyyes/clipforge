// Undo/redo over immutable timeline snapshots. Snapshots share structure
// (ops copy only what they change), so keeping 200 of them is cheap.

export class History<T> {
  private past: { state: T; label: string }[] = [];
  private future: { state: T; label: string }[] = [];
  constructor(private limit = 200) {}

  push(prev: T, label: string): void {
    this.past.push({ state: prev, label });
    if (this.past.length > this.limit) this.past.shift();
    this.future = [];
  }

  undo(current: T): { state: T; label: string } | null {
    const e = this.past.pop();
    if (!e) return null;
    this.future.push({ state: current, label: e.label });
    return e;
  }

  redo(current: T): { state: T; label: string } | null {
    const e = this.future.pop();
    if (!e) return null;
    this.past.push({ state: current, label: e.label });
    return e;
  }

  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
  get undoLabel() { return this.past[this.past.length - 1]?.label; }
  get redoLabel() { return this.future[this.future.length - 1]?.label; }
  clear() { this.past = []; this.future = []; }
}
