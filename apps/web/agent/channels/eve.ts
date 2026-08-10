import { eveChannel } from "eve/channels/eve";
import { localDev, none } from "eve/channels/auth";

/**
 * Local-first research tool: authenticate eve-dev/vercel-dev sessions and
 * allow anonymous local access (no auth required on localhost).
 * Add stricter auth before any public deployment.
 */
export default eveChannel({ auth: [localDev(), none()] });