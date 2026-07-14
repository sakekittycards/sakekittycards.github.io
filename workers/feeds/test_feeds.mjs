// Verifies the REAL feeds worker (imported, not re-implemented) against the live
// YouTube RSS plus a fake KV and an injected poster.
import {
  parseYouTube, syncFeed, syncSquare, igEmbed, ytEmbed, squareEmbed,
} from "./worker.js";

let fails = 0;
const ok = (cond, msg) => { console.log(`${cond ? "  PASS" : "  FAIL"}  ${msg}`); if (!cond) fails++; };
const makeKV = () => {
  const m = new Map();
  return { get: async (k) => m.get(k) ?? null, put: async (k, v) => void m.set(k, v), _m: m };
};
const feed = (items) => async () => items;

// ── 1. parse the live RSS ────────────────────────────────────────────────────
console.log("\n[1] parseYouTube against the live channel feed");
const xml = await (await fetch(
  "https://www.youtube.com/feeds/videos.xml?channel_id=UCAwRh1yzSzU4SW4ecEdmbDw"
)).text();
const items = parseYouTube(xml);
ok(items.length > 0, `parsed ${items.length} entries`);
ok(items.every((i) => /^[\w-]{11}$/.test(i.id)), "every id looks like a YouTube video id");
ok(items.every((i) => i.title && i.title !== "New video"), "every entry has a real title");
ok(items.every((i) => i.published > 0), "every entry has a parsed timestamp");
ok(!items.some((i) => /&(amp|quot|#39|lt|gt);/.test(i.title)), "XML entities decoded in titles");
console.log(`  newest: ${[...items].sort((a, b) => b.published - a.published)[0].title}`);

// ── 2. real syncFeed: bootstrap + de-dupe ────────────────────────────────────
console.log("\n[2] real syncFeed (fake KV, injected poster)");
const kv = makeKV();
const env = { FEEDS: kv };
let posted = [];
const spy = async (_hook, payload) => void posted.push(payload);

await syncFeed(env, "yt", feed(items), "http://hook", ytEmbed, spy);
ok(posted.length === 0, `first run posts nothing (bootstrap) — posted ${posted.length}`);
ok(kv._m.has("bootstrap:yt"), "bootstrap flag written");
ok([...kv._m.keys()].filter((k) => k.startsWith("seen:yt:")).length === items.length,
   "all existing videos marked seen on bootstrap");

posted = [];
await syncFeed(env, "yt", feed(items), "http://hook", ytEmbed, spy);
ok(posted.length === 0, "second run, no new videos, posts nothing");

const fresh = { id: "NEWVIDEO123", title: "Brand New", url: "https://www.youtube.com/watch?v=NEWVIDEO123", published: Date.now() };
posted = [];
await syncFeed(env, "yt", feed([fresh, ...items]), "http://hook", ytEmbed, spy);
ok(posted.length === 1, `a new video posts exactly once — posted ${posted.length}`);
ok(posted[0].content.includes("NEWVIDEO123"), "payload carries the new video url");

posted = [];
await syncFeed(env, "yt", feed([fresh, ...items]), "http://hook", ytEmbed, spy);
ok(posted.length === 0, "the same new video does not post again");

// ── 3. failed post must retry next run (not be marked seen) ──────────────────
console.log("\n[3] a Discord failure must not swallow the post");
const kv3 = makeKV();
const env3 = { FEEDS: kv3 };
await kv3.put("bootstrap:yt", "now");
const boom = async () => { throw new Error("discord 500"); };
await syncFeed(env3, "yt", feed([fresh]), "http://hook", ytEmbed, boom).catch(() => {});
ok(!kv3._m.has(`seen:yt:${fresh.id}`), "failed post is NOT marked seen");
posted = [];
await syncFeed(env3, "yt", feed([fresh]), "http://hook", ytEmbed, spy);
ok(posted.length === 1, "and it posts on the next run once Discord recovers");

// ── 4. no webhook configured = inert ─────────────────────────────────────────
console.log("\n[4] unconfigured feed stays inert");
const kv4 = makeKV();
posted = [];
await syncFeed({ FEEDS: kv4 }, "ig", feed([fresh]), undefined, igEmbed, spy);
ok(posted.length === 0 && kv4._m.size === 0, "no webhook => no posts, no KV writes");

// ── 5. backlog cap ───────────────────────────────────────────────────────────
console.log("\n[5] backlog cap");
const kv5 = makeKV();
await kv5.put("bootstrap:yt", "now");
const flood = Array.from({ length: 20 }, (_, n) => ({ id: `v${n}`, title: `v${n}`, url: `u${n}`, published: n }));
posted = [];
await syncFeed({ FEEDS: kv5 }, "yt", feed(flood), "http://hook", ytEmbed, spy);
ok(posted.length === 5, `capped at 5 per run — posted ${posted.length}`);
ok(posted[0].content.includes("u15"), "cap keeps the NEWEST, oldest-first within the batch");

// ── 6. IG embed shape (Discord rejects oversized fields) ─────────────────────
console.log("\n[6] igEmbed payload shape");
const long = "x".repeat(3000);
const e = igEmbed({ id: "1", title: long, caption: long, url: "https://instagram.com/p/abc", thumb: "https://t/1.jpg", published: Date.now() });
ok(e.embeds[0].title.length <= 240, `title truncated to ${e.embeds[0].title.length} (<=240)`);
ok(e.embeds[0].description.length <= 500, `description truncated to ${e.embeds[0].description.length} (<=500)`);
ok(e.embeds[0].url === "https://instagram.com/p/abc", "permalink preserved");
const noThumb = igEmbed({ id: "2", title: "t", caption: "", url: "u", thumb: null, published: 0 });
ok(noThumb.embeds[0].image === undefined, "missing thumb omits the image field entirely");

// ── 7. shop feed: new product + restock transitions ──────────────────────────
console.log("\n[7] syncSquare new-product / restock transitions");
const P = (id, inStock, createdAt = 1) => ({ id, name: `item ${id}`, description: "d", price: 10, image: null, inStock, createdAt });
const kvS = makeKV();
const envS = { FEEDS: kvS };
posted = [];

// baseline: 2 in stock, 1 out
const base = [P("a", true), P("b", true), P("c", false)];
await syncSquare(envS, feed(base), "http://hook", spy);
ok(posted.length === 0, `bootstrap posts nothing — posted ${posted.length}`);
ok(kvS._m.get("sq:c") === "0", "out-of-stock item recorded as 0 at baseline");

// nothing changed
posted = [];
await syncSquare(envS, feed(base), "http://hook", spy);
ok(posted.length === 0, "no changes => no posts");

// c comes back in stock -> restock
posted = [];
await syncSquare(envS, feed([P("a", true), P("b", true), P("c", true)]), "http://hook", spy);
ok(posted.length === 1, `restock posts once — posted ${posted.length}`);
ok(posted[0].content.includes("Back in stock"), "restock uses the restock copy");
ok(kvS._m.get("sq:c") === "1", "restock updates stored stock state");

posted = [];
await syncSquare(envS, feed([P("a", true), P("b", true), P("c", true)]), "http://hook", spy);
ok(posted.length === 0, "restock does not re-post while it stays in stock");

// a brand-new product id appears
posted = [];
await syncSquare(envS, feed([...base, P("d", true, 999)]), "http://hook", spy);
ok(posted.length === 1, `new product posts once — posted ${posted.length}`);
ok(posted[0].content.includes("New in the shop"), "new product uses the new-product copy");

posted = [];
await syncSquare(envS, feed([...base, P("d", true, 999)]), "http://hook", spy);
ok(posted.length === 0, "new product does not post twice");

// a product going OUT of stock is silent, but arms the next restock
posted = [];
await syncSquare(envS, feed([P("a", false), P("b", true), P("c", false), P("d", true, 999)]), "http://hook", spy);
ok(posted.length === 0, "going out of stock is silent (no 'sold out' spam)");
ok(kvS._m.get("sq:a") === "0", "…but the OOS state is recorded");
posted = [];
await syncSquare(envS, feed([P("a", true), P("b", true), P("c", false), P("d", true, 999)]), "http://hook", spy);
ok(posted.length === 1 && posted[0].content.includes("Back in stock"), "…so its return fires a restock");

// unconfigured shop feed
const kvS2 = makeKV();
posted = [];
await syncSquare({ FEEDS: kvS2 }, feed(base), undefined, spy);
ok(posted.length === 0 && kvS2._m.size === 0, "no site webhook => inert, no KV writes");

// ── 8. squareEmbed shape ─────────────────────────────────────────────────────
console.log("\n[8] squareEmbed payload shape");
const se = squareEmbed({ kind: "new", item: { id: "XYZ", name: "n".repeat(300), description: "d".repeat(400), price: 59.99, image: "https://i/1.jpg", createdAt: 0 } });
ok(se.embeds[0].url === "https://sakekittycards.com/product.html?id=XYZ", "links to the product page");
ok(se.embeds[0].title.length <= 240, `title truncated to ${se.embeds[0].title.length}`);
ok(se.embeds[0].description.length <= 300, `description truncated to ${se.embeds[0].description.length}`);
ok(se.embeds[0].fields[0].value === "$59.99", "price rendered");
const noImg = squareEmbed({ kind: "restock", item: { id: "Q", name: "q", description: "", price: null, image: null, createdAt: 0 } });
ok(noImg.embeds[0].image === undefined && noImg.embeds[0].fields === undefined, "missing image/price omit their fields");

console.log(fails === 0 ? "\nALL PASS\n" : `\n${fails} FAILURE(S)\n`);
process.exit(fails === 0 ? 0 : 1);
