import { useCallback, useEffect, useRef, useState } from "react";
import type { LineOut, ShapeOut } from "../api";
import { humanLabel } from "../uiLabels";

interface Props {
  shapes: ShapeOut[];
  lines: LineOut[];
  onGenerate: (text: string, entityType: string, relationType: string) => void;
}

// The Web Speech API ships prefixed in Chromium and has no lib.dom typing that
// is stable across TS versions, so the constructor is resolved dynamically.
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((ev: any) => void) | null;
  onerror: ((ev: any) => void) | null;
  onend: (() => void) | null;
};

function getRecognitionCtor(): (new () => Recognition) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const LANGS: [string, string][] = [
  ["en-US", "English (US)"],
  ["en-IN", "English (India)"],
  ["hi-IN", "Hindi"],
];

// Spoken descriptions arrive as one run-on line. Split it into steps on
// sentence punctuation and on the connectives people naturally narrate with
// ("then", "after that", …), so the plan starts as one line per step.
const STEP_SPLIT =
  /(?:[.!?;\n]+|,?\s+(?:and then|then|after that|after which|next|followed by|finally|lastly|first of all|firstly|secondly|thirdly)\s+)/i;

function transcriptToPlan(transcript: string): string {
  const cleaned = transcript.replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  const steps = cleaned
    .split(new RegExp(STEP_SPLIT.source, "gi"))
    .map((s) => s.trim().replace(/^(?:and|also|so|okay|ok|um|uh)\s+/i, ""))
    .filter((s) => s.length > 1)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1));
  if (steps.length === 0) return "";
  if (steps.length === 1) return steps[0];
  const [root, ...rest] = steps;
  return [root, ...rest.map((s) => `  ${s}`)].join("\n");
}

export default function VoicePanel({ shapes, lines, onGenerate }: Props) {
  const supported = getRecognitionCtor() !== null;
  const [recording, setRecording] = useState(false);
  const [interim, setInterim] = useState("");
  const [transcript, setTranscript] = useState("");
  const [plan, setPlan] = useState("");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [lang, setLang] = useState("en-US");
  const [entityType, setEntityType] = useState("process");
  const [relationType, setRelationType] = useState("sequence_flow");
  const recRef = useRef<Recognition | null>(null);

  // Keep the type selects valid for whatever palette the open workbook has.
  useEffect(() => {
    if (shapes.length && !shapes.some((s) => s.entity_type === entityType)) {
      setEntityType(shapes[0].entity_type);
    }
  }, [shapes, entityType]);
  useEffect(() => {
    if (lines.length && !lines.some((l) => l.relation_type === relationType)) {
      setRelationType(lines[0].relation_type);
    }
  }, [lines, relationType]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    recRef.current = null;
    setRecording(false);
    setInterim("");
  }, []);

  useEffect(() => stop, [stop]); // stop the mic if the panel unmounts mid-recording

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    setVoiceError(null);
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (ev: any) => {
      let interimText = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) {
          const chunk = String(res[0].transcript).trim();
          if (chunk) setTranscript((cur) => (cur ? `${cur} ${chunk}` : chunk));
        } else {
          interimText += res[0].transcript;
        }
      }
      setInterim(interimText);
    };
    rec.onerror = (ev: any) => {
      if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
        setVoiceError("Microphone access was blocked. Allow the mic for this site in your browser and try again.");
      } else if (ev.error !== "no-speech" && ev.error !== "aborted") {
        setVoiceError(`Voice input stopped (${ev.error}). Try again.`);
      }
    };
    // Chrome ends recognition on its own after a silence; reflect that in the
    // button instead of silently pretending the mic is still hot.
    rec.onend = () => {
      recRef.current = null;
      setRecording(false);
      setInterim("");
    };
    recRef.current = rec;
    setRecording(true);
    rec.start();
  }, [lang]);

  const onBuildPlan = () => setPlan(transcriptToPlan(transcript));

  const onCopyPlan = () => {
    navigator.clipboard?.writeText(plan).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  if (!supported) {
    return (
      <div className="panel">
        <h3>Voice planner</h3>
        <p className="hint">
          This browser doesn't support voice input. Use Chrome or Edge — or type your plan in the
          Outline tab instead.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3>Voice planner</h3>
      <p className="hint">
        Describe the diagram you need out loud — "first the customer places an order, then we check
        stock, then…". Your words become an editable plan, and the plan becomes a diagram.
      </p>

      <label className="field">
        <span>Language</span>
        <select value={lang} onChange={(e) => setLang(e.target.value)} disabled={recording}>
          {LANGS.map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <button
        className={`btn voice-mic ${recording ? "recording" : ""}`}
        onClick={recording ? stop : start}
        aria-pressed={recording}
      >
        <span className="voice-dot" aria-hidden="true" />
        {recording ? "Stop listening" : "Start speaking"}
      </button>
      {recording && <p className="hint voice-live">{interim || "Listening…"}</p>}
      {voiceError && <p className="voice-error">{voiceError}</p>}

      <label className="field">
        <span>What you said (editable)</span>
        <textarea
          rows={5}
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Your speech appears here…"
          spellCheck={false}
        />
      </label>
      <div className="btn-row">
        <button className="btn" onClick={onBuildPlan} disabled={!transcript.trim()}>
          Turn into plan
        </button>
        <button
          className="btn"
          onClick={() => {
            setTranscript("");
            setPlan("");
          }}
          disabled={!transcript && !plan}
        >
          Clear
        </button>
      </div>

      <label className="field">
        <span>Plan (one step per line — edit freely, indent with 2 spaces to nest)</span>
        <textarea
          rows={8}
          value={plan}
          onChange={(e) => setPlan(e.target.value)}
          placeholder="Steps show up here after 'Turn into plan'…"
          spellCheck={false}
        />
      </label>

      <label className="field">
        <span>Node type</span>
        <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
          {shapes.map((s) => (
            <option key={s.entity_type} value={s.entity_type}>
              {humanLabel(s.entity_type)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Connection type</span>
        <select value={relationType} onChange={(e) => setRelationType(e.target.value)}>
          {lines.map((l) => (
            <option key={l.relation_type} value={l.relation_type}>
              {humanLabel(l.relation_type)}
            </option>
          ))}
        </select>
      </label>

      <div className="btn-row">
        <button
          className="btn btn-primary"
          onClick={() => onGenerate(plan, entityType, relationType)}
          disabled={!plan.trim()}
        >
          Generate diagram from plan
        </button>
        <button className="btn" onClick={onCopyPlan} disabled={!plan.trim()}>
          {copied ? "Copied!" : "Copy plan"}
        </button>
      </div>
      <p className="hint">
        Generating starts a fresh diagram from the plan — save your current work first if you need
        it.
      </p>
    </div>
  );
}
