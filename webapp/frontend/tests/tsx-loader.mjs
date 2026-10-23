// Compile component contracts in Node without adding a browser/test dependency.
import { accessSync, readFileSync } from "node:fs";
import ts from "typescript";

function resolveTypescript(specifier, context, error) {
  if (!specifier.startsWith(".")) throw error;
  for (const extension of [".tsx", ".ts"]) {
    const url = new URL(specifier + extension, context.parentURL);
    try {
      accessSync(url);
      return { url: url.href, shortCircuit: true };
    } catch { /* Try the next TypeScript extension. */ }
  }
  throw error;
}

export function resolveSync(specifier, context, nextResolve) {
  try {
    return nextResolve(specifier, context);
  } catch (error) {
    return resolveTypescript(specifier, context, error);
  }
}

// Node 20's registered loader hooks use asynchronous resolution.
export async function resolve(specifier, context, nextResolve) {
  try { return await nextResolve(specifier, context); }
  catch (error) { return resolveTypescript(specifier, context, error); }
}

export function load(url, context, nextLoad) {
  if (!/\.tsx?$/.test(url)) return nextLoad(url, context);
  const source = readFileSync(new URL(url), "utf8");
  const result = ts.transpileModule(source.replaceAll("import.meta.env", "({})"), {
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
    fileName: new URL(url).pathname,
  });
  return { format: "module", source: result.outputText, shortCircuit: true };
}
