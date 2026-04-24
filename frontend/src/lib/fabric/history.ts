export class HistoryManager {
  private undoStack: string[] = [];
  private redoStack: string[] = [];
  private maxStackSize = 50;
  private onSave: (json: string) => string;
  private onRestore: (json: string) => void;
  private ignoreNextChange = false;

  constructor(onSave: (json: string) => string, onRestore: (json: string) => void) {
    this.onSave = onSave;
    this.onRestore = onRestore;
  }

  pushState() {
    if (this.ignoreNextChange) {
      this.ignoreNextChange = false;
      return;
    }
    const json = this.onSave('');
    this.undoStack.push(json);
    if (this.undoStack.length > this.maxStackSize) {
      this.undoStack.shift();
    }
    this.redoStack = [];
  }

  undo() {
    if (this.undoStack.length === 0) return;
    const state = this.undoStack.pop()!;
    this.redoStack.push(this.onSave(''));
    this.ignoreNextChange = true;
    this.onRestore(state);
  }

  redo() {
    if (this.redoStack.length === 0) return;
    const state = this.redoStack.pop()!;
    this.undoStack.push(this.onSave(''));
    this.ignoreNextChange = true;
    this.onRestore(state);
  }

  canUndo(): boolean {
    return this.undoStack.length > 0;
  }

  canRedo(): boolean {
    return this.redoStack.length > 0;
  }

  clear() {
    this.undoStack = [];
    this.redoStack = [];
  }
}
