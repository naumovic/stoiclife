// FEAT-07 stoic-coach-ui: a thin shim (docs/FEAT07-UX-TELEGRAM-SEED.md G6).
//
// Claims the `sc` callback namespace and four slash commands on the coach bot's
// Telegram account, pipes each one as JSON to sc_dispatch.py, and applies the
// actions it prints. Nothing here reaches the LLM. Keep this file dumb: changing
// it needs a gateway restart, changing sc_dispatch.py doesn't.
import { spawn } from "node:child_process";

const PYTHON = "/usr/bin/python3";
const STOICLIFE = "/home/mihajlo/projects/stoiclife";
const DISPATCH = `${STOICLIFE}/sc_dispatch.py`;
const COACH_ACCOUNT = "coach";
const TIMEOUT_MS = 20000;

const COMMANDS = [
  { name: "mood", description: "Log today's mood (1-10)" },
  { name: "module", description: "Pick a Stoic module" },
  { name: "journal", description: "Write a journal entry now" },
  { name: "skip", description: "Skip the pending prep/review" },
];

function runDispatch(input) {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [DISPATCH], { cwd: STOICLIFE, stdio: ["pipe", "pipe", "pipe"] });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`sc_dispatch timed out after ${TIMEOUT_MS}ms`));
    }, TIMEOUT_MS);
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(`sc_dispatch exit ${code}: ${err.slice(-400)}`));
      try {
        resolve(JSON.parse(out.trim().split("\n").pop() || "{}"));
      } catch (e) {
        reject(new Error(`sc_dispatch bad JSON: ${out.slice(-400)}`));
      }
    });
    child.stdin.end(JSON.stringify(input));
  });
}

async function applyActions(respond, actions) {
  for (const a of actions ?? []) {
    if (a.type === "edit") await respond.editMessage({ text: a.text, buttons: a.buttons });
    else if (a.type === "editButtons") await respond.editButtons({ buttons: a.buttons ?? [] });
    else if (a.type === "clearButtons") await respond.clearButtons();
    else if (a.type === "reply") await respond.reply({ text: a.text, buttons: a.buttons });
  }
}

export default {
  id: "stoic-coach-ui",
  name: "Stoic coach UI",
  description: "Deterministic sc: buttons and slash commands for the Stoic coach bot",

  register(api) {
    const log = api.logger;

    api.registerInteractiveHandler({
      channel: "telegram",
      namespace: "sc",
      handler: async (ctx) => {
        // G17: sc: taps are ours wherever they land; swallow them rather than let
        // another agent see "callback_data: sc:…".
        if (ctx.accountId !== COACH_ACCOUNT) {
          log.warn(`stoic-coach-ui: sc callback on account ${ctx.accountId}; ignored`);
          return { handled: true };
        }
        if (!ctx.auth?.isAuthorizedSender) {
          log.warn(`stoic-coach-ui: unauthorized sc callback from ${ctx.senderId}; ignored`);
          return { handled: true };
        }
        try {
          const out = await runDispatch({
            kind: "callback",
            data: ctx.callback.data,
            payload: ctx.callback.payload,
            chatId: ctx.callback.chatId,
            messageId: ctx.callback.messageId,
            messageText: ctx.callback.messageText,
            senderId: ctx.senderId,
            accountId: ctx.accountId,
          });
          await applyActions(ctx.respond, out.actions);
          // D44: a hold tap is passed on, so OpenClaw sends `callback_data: sc:hold:…` through
          // the normal pipeline and the coach gets the held text via the route line.
          if (out.passToAgent) return { handled: false };
        } catch (e) {
          log.error(`stoic-coach-ui: ${ctx.callback.data}: ${e?.message ?? e}`);
        }
        return { handled: true };
      },
    });

    for (const cmd of COMMANDS) {
      api.registerCommand({
        name: cmd.name,
        description: cmd.description,
        channels: ["telegram"],
        acceptsArgs: true,
        handler: async (ctx) => {
          if (ctx.accountId && ctx.accountId !== COACH_ACCOUNT) return { continueAgent: true };
          if (!ctx.isAuthorizedSender) return { text: "Not authorised." };
          try {
            const out = await runDispatch({
              kind: "command",
              command: cmd.name,
              args: ctx.args ?? "",
              chatId: ctx.from ?? ctx.to,
              senderId: ctx.senderId,
            });
            // P3-D3: pass the dispatcher's reply through untouched (text, channelData,
            // presentation), so new reply shapes never need a shim change + restart.
            if (out.reply && typeof out.reply === "object") return out.reply;
            return { text: out.text ?? "" };
          } catch (e) {
            log.error(`stoic-coach-ui: /${cmd.name}: ${e?.message ?? e}`);
            return { text: "Something went wrong; it's logged." };
          }
        },
      });
    }
    // FEAT-07 Phase 4 (D41): route every coach-chat message in two hooks OpenClaw awaits.
    // before_dispatch runs before the agent is dispatched: route_entry decides and records
    // the route, and may handle the message outright (notes "Thanks, noted.", D42) or hold
    // it for a confirm tap (D44). before_prompt_build runs before the model call and puts
    // the recorded route (with the message text, D43) into the coach's prompt.
    api.on("before_dispatch", async (event, ctx) => {
      if (ctx?.channelId !== "telegram" || ctx?.accountId !== COACH_ACCOUNT || event?.isGroup) return;
      try {
        const out = await runDispatch({
          kind: "dispatch",
          text: event.content ?? "",
          replyToId: event.replyToId ?? ctx.replyToId,
          chatId: ctx.conversationId ?? event.senderId,
          sessionKey: ctx.sessionKey ?? event.sessionKey,
        });
        if (out?.handled) return out.text ? { handled: true, text: out.text } : { handled: true };
      } catch (e) {
        log.error(`stoic-coach-ui: before_dispatch: ${e?.message ?? e}`);
      }
      return; // not handled: the message goes to the coach as usual
    });

    api.on("before_prompt_build", async (_event, ctx) => {
      if (ctx?.agentId !== "coach" || ctx?.trigger === "cron" || ctx?.trigger === "heartbeat") return;
      try {
        const out = await runDispatch({
          kind: "inject",
          sessionKey: ctx.sessionKey,
          chatId: ctx.chatId ?? ctx.channelId,
        });
        if (out?.prependContext) return { prependContext: out.prependContext };
      } catch (e) {
        log.error(`stoic-coach-ui: before_prompt_build: ${e?.message ?? e}`);
      }
      return;
    });
    // MIN-127/MIN-128: OpenClaw delivers every text block of a turn and drops only an exact
    // NO_REPLY, so narration and "🧭\n\nNO_REPLY" leaked. after_tool_call just records the
    // coach's exec calls per run; sc_dispatch.handle_outbound decides each outgoing payload.
    const runTools = new Map(); // runId -> [{command, output, error}]
    const textOf = (r) => {
      if (r == null) return "";
      if (typeof r === "string") return r;
      if (Array.isArray(r.content)) {
        const t = r.content.filter((p) => p?.type === "text").map((p) => p.text).join("\n");
        const code = r.details?.exitCode;
        return code != null && code !== 0 ? `${t}\n(Command exited with code ${code})` : t;
      }
      try {
        return JSON.stringify(r);
      } catch {
        return String(r);
      }
    };
    api.on("after_tool_call", (event, ctx) => {
      if (ctx?.agentId !== "coach" || event?.toolName !== "exec") return;
      const runId = event.runId ?? ctx.runId;
      if (!runId) return;
      if (!runTools.has(runId)) {
        runTools.set(runId, []);
        if (runTools.size > 50) runTools.delete(runTools.keys().next().value);
      }
      runTools.get(runId).push({
        command: String(event.params?.command ?? "").slice(0, 400),
        output: textOf(event.result).slice(-400),
        error: event.error ?? null,
      });
    });

    api.on("reply_payload_sending", async (event, ctx) => {
      if (ctx?.channelId !== "telegram" || ctx?.accountId !== COACH_ACCOUNT) return;
      const text = event?.payload?.text;
      if (typeof text !== "string" || !text.trim()) return;
      try {
        const out = await runDispatch({
          kind: "outbound",
          text,
          dispatchKind: event.kind,
          tools: runTools.get(event.runId ?? ctx.runId) ?? [],
        });
        if (out?.cancel) return { cancel: true, reason: `stoic-coach-ui: ${out.cancel}` };
        if (typeof out?.text === "string") return { payload: { ...event.payload, text: out.text } };
      } catch (e) {
        log.error(`stoic-coach-ui: reply_payload_sending: ${e?.message ?? e}`);
      }
      return; // fail open: send as is
    });
    log.info("stoic-coach-ui: registered sc namespace, /mood /module /journal /skip, before_dispatch + before_prompt_build + outbound guard");
  },
};
