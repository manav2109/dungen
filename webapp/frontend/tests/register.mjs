import * as module from "node:module";
import { resolveSync, load } from "./tsx-loader.mjs";

if (module.registerHooks) module.registerHooks({ resolve: resolveSync, load });
else module.register("./tsx-loader.mjs", import.meta.url);
