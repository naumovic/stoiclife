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
    // P3-B1: save a pending note / "Tell me more" answer as the message arrives, before
    // the LLM sees it (the coach once misread the message and skipped its step 0).
    // Observe-only hook: the agent still gets the message and acks it.
    api.on("message_received", async (event, ctx) => {
      if (ctx?.channelId !== "telegram" || ctx?.accountId !== COACH_ACCOUNT) return;
      try {
        await runDispatch({
          kind: "message",
          text: event.content ?? "",
          chatId: event.from ?? ctx.conversationId,
          messageId: event.messageId,
          senderId: event.senderId,
        });
      } catch (e) {
        log.error(`stoic-coach-ui: message hook: ${e?.message ?? e}`);
      }
    });
    log.info("stoic-coach-ui: registered sc namespace + /mood /module /journal /skip + message hook");
  },
};
