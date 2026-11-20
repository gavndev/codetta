// Codetta UI — plain JavaScript, no framework, no build step.
//
// Talks to the JSON API in codetta/web/routes/ (one module per area). The current folder lives in the
// URL hash (#/Artist/Album), so the back button and refresh work.
//
// This file is only the entry point. The page lives in js/, one native ES module per area
// (dom, api, state, browse, editor, player, inbox, library, account, ...). Each module imports
// exactly what it uses from the others and nothing needs building. Start reading at boot() in
// js/account.js; the buttons and keys are connected in js/wiring.js.

import { boot } from "./js/account.js";

boot();
