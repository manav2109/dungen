import { useEffect, useRef, useState } from "react";

export default function SaveDialog({ initialName, onSave, onClose }: {
  initialName: string;
  onSave: (name: string) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(initialName);
  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previousFocus?.focus();
    };
  }, []);
  return (
    <dialog ref={dialogRef} className="save-dialog" aria-labelledby="save-dialog-title" aria-describedby="save-dialog-description" onCancel={onClose} onKeyDown={(event) => {
      // WebView hosts do not all trigger a native dialog cancel on Escape.
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); }
    }}>
      <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) { onSave(name.trim()); onClose(); } }}>
        <p className="eyebrow">Your workspace</p>
        <h2 id="save-dialog-title">Save your diagram</h2>
        <p id="save-dialog-description" className="hint">Give this project a name so you can reopen it later.</p>
        <label className="field"><span>Project name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={200} required /></label>
        <div className="dialog-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button type="submit" className="btn btn-primary" disabled={!name.trim()}>Save diagram</button></div>
      </form>
    </dialog>
  );
}
