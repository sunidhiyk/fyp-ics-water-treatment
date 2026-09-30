// Builds report/FYP_Final_Presentation.pptx (16:9, ~15 slides, speaker notes).
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "report", "FYP_Final_Presentation.pptx");

// palette: deep water navy dominates, teal supports, alert red for attacks
const NAVY = "0B2545", TEAL = "13678A", TEAL_LT = "D8ECEF", MINT = "3DB4A5",
  RED = "D64545", RED_LT = "FBE3E1", INK = "1B263B", MUTED = "5C6B7A", CARD = "F1F6F8", WHITE = "FFFFFF";
const HEAD = "Cambria", BODY = "Calibri";
const W = 13.333, H = 7.5, M = 0.6;
const TOTAL = 15;

// ---------------------------------------------------------------- helpers
const iconCache = {};
async function icon(name, hex = WHITE) {
  const key = name + hex;
  if (iconCache[key]) return iconCache[key];
  const Comp = fa[name];
  if (!Comp) throw new Error("missing icon " + name);
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { size: 256, color: "#" + hex }));
  const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return (iconCache[key] = "image/png;base64," + png.toString("base64"));
}
async function circleIcon(slide, name, x, y, d, fill, fg = WHITE) {
  slide.addShape("ellipse", { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
  const s = d * 0.52;
  slide.addImage({ data: await icon(name, fg), x: x + (d - s) / 2, y: y + (d - s) / 2, w: s, h: s });
}
function pngSize(p) { const b = fs.readFileSync(p); return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) }; }
// place an image inside a box, preserving aspect ratio, centred
function fitImage(slide, rel, bx, by, bw, bh, extra = {}) {
  const file = path.join(ROOT, rel);
  const { w, h } = pngSize(file);
  const r = Math.min(bw / w, bh / h);
  const iw = w * r, ih = h * r;
  slide.addImage({ path: file, x: bx + (bw - iw) / 2, y: by + (bh - ih) / 2, w: iw, h: ih, ...extra });
  return { x: bx + (bw - iw) / 2, y: by + (bh - ih) / 2, w: iw, h: ih };
}
function title(slide, text, sub) {
  slide.addText(text, { x: M, y: 0.38, w: W - 2 * M, h: 0.8, fontFace: HEAD, fontSize: 32, bold: true,
    color: NAVY, margin: 0, valign: "middle", isTextBox: true });
  if (sub) slide.addText(sub, { x: M, y: 1.14, w: W - 2 * M, h: 0.45, fontFace: BODY, fontSize: 16,
    color: MUTED, margin: 0, isTextBox: true });
}
function pageNo(slide, n, dark = false) {
  slide.addText(`${n} / ${TOTAL}`, { x: W - 1.6, y: H - 0.5, w: 1.0, h: 0.3, fontFace: BODY, fontSize: 10,
    color: dark ? "9FB3C8" : "8A97A6", align: "right", margin: 0, isTextBox: true });
}
function card(slide, x, y, w, h, fill = CARD) {
  slide.addShape("roundRect", { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.08 });
}
const bullets = (items, o = {}) => items.map((t, i) => ({
  text: t, options: { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: 8, ...o },
}));

// ---------------------------------------------------------------- slides
async function build() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "Real-Time Cyber-Attack Detection for a Water Treatment ICS";

  // 1 ---------------------------------------------------------- title
  let s = pres.addSlide(); s.background = { color: NAVY };
  s.addText("FINAL YEAR PROJECT", { x: M, y: 1.0, w: 8, h: 0.4, fontFace: BODY, fontSize: 14, bold: true,
    color: MINT, charSpacing: 4, margin: 0, isTextBox: true });
  s.addText("Real-Time Cyber-Attack Detection for a Water Treatment ICS", { x: M, y: 1.5, w: 8.3, h: 1.9,
    fontFace: HEAD, fontSize: 40, bold: true, color: WHITE, margin: 0, valign: "top", isTextBox: true });
  s.addText("A protocol-aware and deep-learning detection-in-depth framework with tamper-evident logging",
    { x: M, y: 3.7, w: 8.0, h: 0.8, fontFace: BODY, fontSize: 18, italic: true, color: "C9D6E3", margin: 0, isTextBox: true });
  s.addText([
    { text: "[Member Name 1]  ·  [Member Name 2]  ·  [Member Name 3]  ·  [Member Name 4]", options: { breakLine: true } },
    { text: "Supervisor: [Supervisor Name]", options: { breakLine: true } },
    { text: "[University Name]  ·  [Month Year]" },
  ], { x: M, y: 5.15, w: 8.3, h: 1.3, fontFace: BODY, fontSize: 15, color: WHITE, margin: 0, paraSpaceAfter: 6, isTextBox: true });
  await circleIcon(s, "FaTint", 9.35, 1.55, 2.9, TEAL);
  await circleIcon(s, "FaShieldAlt", 11.05, 3.65, 1.45, RED);
  s.addNotes("Our project detects cyber-attacks on the control network of a water treatment plant. Because we had no hardware, we built the whole plant, network and attacks in software, then designed three detection layers and a tamper-proof log, and evaluated them on our own data and on a public dataset from a real testbed.");

  // 2 ---------------------------------------------------------- problem
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Industrial protocols trust anyone on the network");
  s.addText(bullets([
    "Plants are run by PLCs that read sensors and switch pumps and valves over protocols such as Modbus, EtherNet/IP and DNP3.",
    "These protocols have no authentication: a PLC obeys any well-formed request from any host that can reach it.",
    "An attacker on the control network can fake sensor readings, send unauthorised commands, replay old commands or flood the PLC.",
  ]), { x: M, y: 1.5, w: 5.4, h: 5.2, fontFace: BODY, fontSize: 19, color: INK, valign: "top", margin: 0, isTextBox: true });
  const inc = [
    ["FaMicrochip", "Stuxnet", "Altered PLC logic while showing operators normal-looking data"],
    ["FaBolt", "Ukraine grid, 2015–16", "Attackers opened breakers and cut power"],
    ["FaTint", "Oldsmar, Florida, 2021", "Remote access to a water plant's controls"],
    ["FaIndustry", "Muleshoe, Texas, 2024", "Intrusion into a water facility's controls"],
  ];
  for (let i = 0; i < 4; i++) {
    const cx = 6.55 + (i % 2) * 3.2, cy = 1.5 + Math.floor(i / 2) * 2.7;
    card(s, cx, cy, 2.95, 2.45);
    await circleIcon(s, inc[i][0], cx + 0.25, cy + 0.25, 0.62, RED);
    s.addText(inc[i][1], { x: cx + 0.25, y: cy + 0.98, w: 2.5, h: 0.4, fontFace: BODY, fontSize: 16, bold: true, color: INK, margin: 0, isTextBox: true });
    s.addText(inc[i][2], { x: cx + 0.25, y: cy + 1.4, w: 2.5, h: 0.9, fontFace: BODY, fontSize: 14, color: MUTED, margin: 0, valign: "top", isTextBox: true });
  }
  pageNo(s, 2);
  s.addNotes("The core problem is that industrial protocols like Modbus have no authentication. Whoever can reach the PLC can command it. Real incidents such as Stuxnet, the Ukrainian grid attacks and intrusions at the Oldsmar and Muleshoe water facilities show these are practical threats, not theory.");

  // 3 ---------------------------------------------------------- approach
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Our approach: detection in depth", "Each layer covers attacks the others cannot see");
  const layers = [
    ["FaSearch", TEAL, "DPI rule engine", "Decodes every Modbus write and names the source, device and value"],
    ["FaTachometerAlt", "B7791F", "Flow monitor", "Counts requests per source to catch floods"],
    ["FaBrain", "6B3FB0", "LSTM autoencoder", "Learns normal plant behaviour to catch stealthy manipulation"],
    ["FaLock", MINT, "Tamper-evident ledger", "Hash-chained, signed record of every command and alert"],
  ];
  for (let i = 0; i < 4; i++) {
    const cx = M + i * 3.06, cy = 1.95;
    card(s, cx, cy, 2.86, 3.35);
    await circleIcon(s, layers[i][0], cx + 0.95, cy + 0.35, 0.95, layers[i][1]);
    s.addText(layers[i][2], { x: cx + 0.2, y: cy + 1.5, w: 2.46, h: 0.5, fontFace: BODY, fontSize: 17, bold: true, color: INK, align: "center", margin: 0, isTextBox: true });
    s.addText(layers[i][3], { x: cx + 0.2, y: cy + 2.05, w: 2.46, h: 1.1, fontFace: BODY, fontSize: 13, color: MUTED, align: "center", valign: "top", margin: 0, isTextBox: true });
  }
  s.addText([
    { text: "Constraint: ", options: { bold: true, color: RED } },
    { text: "no ICS hardware was available, so the plant, network, attacker and detectors are all software.", options: { color: INK } },
  ], { x: M, y: 5.75, w: W - 2 * M, h: 0.5, fontFace: BODY, fontSize: 16, margin: 0, isTextBox: true });
  pageNo(s, 3);
  s.addNotes("We follow a detection-in-depth design. A protocol-aware rule engine inspects every write, a flow monitor watches traffic volume, and an LSTM learns what normal plant behaviour looks like. Every command and alert goes into a tamper-evident ledger. The key constraint was no hardware, so everything is software.");

  // 4 ---------------------------------------------------------- substitutions
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "No hardware: what we built instead");
  const subs = [
    ["Physical testbed (SWaT)", "Python model of five coupled treatment stages"],
    ["EtherNet/IP (CIP) traffic", "Modbus TCP: same weaknesses, open tooling"],
    ["MATLAB/Simulink, OpenPLC", "Python process model and controller"],
    ["Hyperledger Fabric", "Signed SHA-256 hash chain behind a ledger interface"],
    ["SWaT dataset (needs approval)", "Own labelled dataset + public HAI 22.04"],
  ];
  s.addText("In the proposal", { x: M, y: 1.35, w: 4.6, h: 0.4, fontFace: BODY, fontSize: 14, bold: true, color: MUTED, margin: 0, isTextBox: true });
  s.addText("What we built", { x: 6.35, y: 1.35, w: 6.3, h: 0.4, fontFace: BODY, fontSize: 14, bold: true, color: TEAL, margin: 0, isTextBox: true });
  for (let i = 0; i < subs.length; i++) {
    const y = 1.85 + i * 0.95;
    card(s, M, y, 4.6, 0.75, "EEF0F2");
    s.addText(subs[i][0], { x: M + 0.25, y, w: 4.2, h: 0.75, fontFace: BODY, fontSize: 15, color: MUTED, valign: "middle", margin: 0, isTextBox: true });
    s.addImage({ data: await icon("FaArrowRight", TEAL), x: 5.5, y: y + 0.2, w: 0.38, h: 0.35 });
    card(s, 6.35, y, 6.38, 0.75, TEAL_LT);
    s.addText(subs[i][1], { x: 6.6, y, w: 6.0, h: 0.75, fontFace: BODY, fontSize: 15, bold: true, color: INK, valign: "middle", margin: 0, isTextBox: true });
  }
  pageNo(s, 4);
  s.addNotes("Each proposal item was replaced by something we could run on a laptop while keeping the part being studied realistic. Modbus has the same security weakness as EtherNet/IP. The hash chain gives the same tamper evidence as a blockchain for a single organisation. SWaT needs an access application, so we used our own dataset plus the public HAI dataset.");

  // 5 ---------------------------------------------------------- architecture
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "System architecture");
  fitImage(s, "report/figures/architecture.png", 1.6, 1.25, W - 3.2, 5.8);
  pageNo(s, 5);
  s.addNotes("The plant simulator exposes its sensors and actuators as Modbus registers. A Python controller acting as the HMI reads and writes them over Modbus TCP, and the attacker sends its own requests. Two logs are recorded: the network log of every request, used by the rule engine and the flow monitor, and a once-per-second device log used by the LSTM. The correlator merges alerts, writes them to the ledger and feeds the dashboard.");

  // 6 ---------------------------------------------------------- plant + attacks
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "A simulated plant under five attacks", "510 s of operation: 60 s normal, then each attack for 45 s with 45 s of normal in between");
  fitImage(s, "report/figures/dataset_timeline.png", M, 1.75, 7.4, 5.0);
  const atk = [
    ["False data injection", "Fakes the tank level (1180 mm)"],
    ["Command injection", "Forces the transfer pump off"],
    ["Flooding (DoS)", "40 read requests per second"],
    ["Replay", "Re-sends a recorded command"],
    ["Stealth", "Compromised HMI holds the acid pump on"],
  ];
  for (let i = 0; i < atk.length; i++) {
    const y = 1.9 + i * 0.98;
    s.addShape("ellipse", { x: 8.45, y: y + 0.08, w: 0.3, h: 0.3, fill: { color: RED }, line: { color: RED } });
    s.addText(atk[i][0], { x: 8.95, y, w: 3.8, h: 0.4, fontFace: BODY, fontSize: 16, bold: true, color: INK, margin: 0, isTextBox: true });
    s.addText(atk[i][1], { x: 8.95, y: y + 0.4, w: 3.8, h: 0.4, fontFace: BODY, fontSize: 13, color: MUTED, margin: 0, isTextBox: true });
  }
  pageNo(s, 6);
  s.addNotes("The plot shows the tank level, pH and two pumps over the run, with attack windows shaded. False data injection fakes the tank level above its limit. Command injection turns the transfer pump off. Flooding sends forty requests a second. Replay re-sends a recorded command. The stealth attack is a compromised HMI holding the acid pump on, which slowly drives the pH down while every request looks valid.");

  // 7 ---------------------------------------------------------- DPI
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Layer 1: protocol-aware rule engine");
  const rules = [
    ["1", "sensor_write", "A write to a sensor register → false data injection"],
    ["2", "unauthorized_writer", "A write from a source other than the HMI → command injection, replay"],
    ["3", "out_of_band_setpoint", "An authorised write with an illegal or out-of-range value"],
  ];
  for (let i = 0; i < 3; i++) {
    const y = 1.45 + i * 1.2;
    card(s, M, y, 6.0, 1.0);
    s.addShape("ellipse", { x: M + 0.22, y: y + 0.2, w: 0.6, h: 0.6, fill: { color: TEAL }, line: { color: TEAL } });
    s.addText(rules[i][0], { x: M + 0.22, y: y + 0.2, w: 0.6, h: 0.6, fontFace: BODY, fontSize: 18, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: rules[i][1], options: { bold: true, color: INK, breakLine: true } }, { text: rules[i][2], options: { color: MUTED } }],
      { x: M + 1.05, y: y + 0.08, w: 4.85, h: 0.85, fontFace: BODY, fontSize: 14, valign: "middle", margin: 0, isTextBox: true });
  }
  card(s, 7.0, 1.45, 5.73, 2.6, RED_LT);
  s.addText("Example alert", { x: 7.3, y: 1.6, w: 5.2, h: 0.4, fontFace: BODY, fontSize: 13, bold: true, color: RED, margin: 0, isTextBox: true });
  s.addText("\u201cUnauthorised source 10.0.0.66 issued a WRITE to P101 (Raw water transfer pump) = 0.0 state, targeting 10.0.0.2. No such source is permitted to command actuators - likely command injection.\u201d",
    { x: 7.3, y: 2.05, w: 5.2, h: 1.9, fontFace: BODY, fontSize: 16, italic: true, color: INK, valign: "top", margin: 0, isTextBox: true });
  s.addText([
    { text: "100%", options: { fontSize: 36, bold: true, color: TEAL, breakLine: true } },
    { text: "of false-data-injection, command-injection and replay writes flagged", options: { fontSize: 13, color: MUTED } },
  ], { x: 7.0, y: 4.45, w: 2.75, h: 1.6, fontFace: BODY, valign: "top", margin: 0, isTextBox: true });
  s.addText([
    { text: "0 / 628", options: { fontSize: 36, bold: true, color: TEAL, breakLine: true } },
    { text: "normal requests flagged", options: { fontSize: 13, color: MUTED } },
  ], { x: 9.95, y: 4.45, w: 2.75, h: 1.6, fontFace: BODY, valign: "top", margin: 0, isTextBox: true });
  s.addText("Blind spots by design: floods of valid reads, and valid commands from the authorised HMI.",
    { x: M, y: 5.25, w: 6.0, h: 0.9, fontFace: BODY, fontSize: 16, color: INK, margin: 0, valign: "top", isTextBox: true });
  pageNo(s, 7);
  s.addNotes("The rule engine decodes every Modbus write and checks three rules, in the spirit of the PA-NIDS paper. Its strength is that alerts say exactly who wrote what to which device. It flagged every false-data-injection, command-injection and replay write, with no false alarms. By design it cannot see floods of reads or valid commands from a compromised HMI; that is what the other two layers are for.");

  // 8 ---------------------------------------------------------- flow + LSTM
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Layers 2 and 3: flow monitor and LSTM");
  card(s, M, 1.4, 5.85, 5.2);
  await circleIcon(s, "FaTachometerAlt", M + 0.3, 1.65, 0.75, "B7791F");
  s.addText("Flow monitor", { x: M + 1.25, y: 1.72, w: 4.3, h: 0.6, fontFace: BODY, fontSize: 20, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(bullets([
    "Counts requests per source per second",
    "Learns a limit from normal traffic only: normal ≤ 3 req/s, threshold 5",
    "The flooding attacker sends 40 req/s",
  ]), { x: M + 0.3, y: 2.65, w: 5.3, h: 2.0, fontFace: BODY, fontSize: 15, color: INK, valign: "top", margin: 0, isTextBox: true });
  s.addText([{ text: "45 / 45", options: { fontSize: 34, bold: true, color: "B7791F", breakLine: true } },
    { text: "flood seconds caught, 0 false alarms", options: { fontSize: 13, color: MUTED } }],
  { x: M + 0.3, y: 4.9, w: 5.2, h: 1.4, fontFace: BODY, margin: 0, valign: "top", isTextBox: true });

  card(s, 6.88, 1.4, 5.85, 5.2);
  await circleIcon(s, "FaBrain", 7.18, 1.65, 0.75, "6B3FB0");
  s.addText("LSTM autoencoder", { x: 8.13, y: 1.72, w: 4.4, h: 0.6, fontFace: BODY, fontSize: 20, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(bullets([
    "Reconstructs 10-second windows of all 22 signals",
    "Trained on normal operation only",
    "Scores a window by its worst-reconstructed signal",
  ]), { x: 7.18, y: 2.65, w: 5.3, h: 2.0, fontFace: BODY, fontSize: 15, color: INK, valign: "top", margin: 0, isTextBox: true });
  s.addText([{ text: "29 → 54 / 54", options: { fontSize: 34, bold: true, color: "6B3FB0", breakLine: true } },
    { text: "stealth windows caught: average error vs worst signal", options: { fontSize: 13, color: MUTED } }],
  { x: 7.18, y: 4.9, w: 5.3, h: 1.4, fontFace: BODY, margin: 0, valign: "top", isTextBox: true });
  pageNo(s, 8);
  s.addNotes("The flow monitor learns normal traffic volume and flags any source far above it; it caught every flood second. The LSTM learns what ten seconds of normal plant behaviour look like. The stealth attack mainly changes one pump and the pH, so averaging the error over all 22 signals hides it: only 29 of 54 windows were caught. Scoring by the worst signal catches all 54, with no false alarms on normal windows.");

  // 9 ---------------------------------------------------------- ledger + dashboard
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Tamper-evident ledger and operator dashboard");
  fitImage(s, "report/figures/dashboard_attack.png", M, 1.35, 6.2, 5.35);
  fitImage(s, "report/figures/ledger_tampered.png", 7.05, 1.35, 5.68, 2.15);
  s.addText(bullets([
    "Each entry is chained to the previous one with SHA-256 and signed with Ed25519",
    "505 commands and alerts recorded; the chain verifies as intact",
    "Editing, deleting, reordering or forging an entry is detected and located",
    "Live demo: inject an attack, then tamper with the log",
  ]), { x: 7.05, y: 3.75, w: 5.68, h: 2.9, fontFace: BODY, fontSize: 15, color: INK, valign: "top", margin: 0, isTextBox: true });
  pageNo(s, 9);
  s.addNotes("On the left is the dashboard during a false data injection: the tank level card is red and the alert is logged. Every command and alert is chained and signed, so if anyone edits the log afterwards, verification fails and points to the altered entry, as in the top-right screenshot. This is the demo we can show live.");

  // 10 --------------------------------------------------------- ablation chart
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Results: no single layer is enough", "Per-second recall and precision on the simulator dataset");
  s.addChart(pres.charts.BAR, [
    { name: "Recall", labels: ["DPI", "Flow monitor", "LSTM", "Combined"], values: [0.6, 0.2, 0.6, 1.0] },
    { name: "Precision", labels: ["DPI", "Flow monitor", "LSTM", "Combined"], values: [1.0, 1.0, 0.833, 0.893] },
  ], {
    x: M, y: 1.75, w: 7.6, h: 4.95, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60,
    chartColors: [TEAL, NAVY], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    dataLabelFontSize: 11, dataLabelColor: INK, valAxisMinVal: 0, valAxisMaxVal: 1.1, valAxisLabelFormatCode: "0.0",
    valAxisLabelColor: MUTED, catAxisLabelColor: INK, catAxisLabelFontSize: 13, valAxisLabelFontSize: 11,
    valGridLine: { color: "E3E8EC", size: 0.75 }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "t", legendFontSize: 12, legendColor: INK,
  });
  const stats = [["1.00", "recall: every attack second flagged"], ["0.89", "precision"], ["0 s", "to the first alert, for every attack"]];
  for (let i = 0; i < 3; i++) {
    const y = 1.8 + i * 1.55;
    card(s, 8.6, y, 4.13, 1.35, TEAL_LT);
    s.addText([{ text: stats[i][0], options: { fontSize: 36, bold: true, color: TEAL, breakLine: true } },
      { text: stats[i][1], options: { fontSize: 13, color: INK } }],
    { x: 8.85, y: y + 0.1, w: 3.7, h: 1.2, fontFace: BODY, valign: "middle", margin: 0, isTextBox: true });
  }
  s.addText("All 27 false-positive seconds are LSTM alerts in the 9 s after an attack ends, while its window still overlaps the attack.",
    { x: 8.6, y: 6.5, w: 4.13, h: 0.7, fontFace: BODY, fontSize: 11, italic: true, color: MUTED, margin: 0, valign: "top", isTextBox: true });
  pageNo(s, 10);
  s.addNotes("This is the ablation. On their own the layers catch at most 60% of attack seconds. Combined they catch every attack second, with 0.89 precision, and raise an alert in the first second of every attack. The only false positives are the nine seconds after some attacks end, when the LSTM's ten-second window still contains attack data.");

  // 11 --------------------------------------------------------- coverage matrix
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Every attack is covered by at least one layer", "Per-second recall by attack class");
  const cols = ["False data injection", "Command injection", "Flooding", "Replay", "Stealth"];
  const grid = [
    ["DPI", [1, 1, 0, 1, 0]], ["Flow monitor", [0, 0, 1, 0, 0]], ["LSTM", [1, 1, 0, 0, 1]], ["Combined", [1, 1, 1, 1, 1]],
  ];
  const hdr = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, align: "center", valign: "middle", fontSize: 14 } });
  const rows = [[hdr("Layer"), ...cols.map(hdr)]];
  for (const [name, vals] of grid) {
    const combined = name === "Combined";
    rows.push([
      { text: name, options: { bold: true, color: INK, fill: { color: combined ? TEAL_LT : "F4F6F8" }, valign: "middle", fontSize: 15 } },
      ...vals.map((v) => ({ text: v ? "100%" : "0%", options: { align: "center", valign: "middle", bold: v === 1, fontSize: 18,
        color: v ? WHITE : "9AA5B1", fill: { color: v ? (combined ? TEAL : MINT) : "F4F6F8" } } })),
    ]);
  }
  s.addTable(rows, { x: M, y: 1.85, w: W - 2 * M, colW: [2.23, 2.0, 2.0, 2.0, 2.0, 1.9], rowH: 0.78,
    fontFace: BODY, border: { type: "solid", pt: 2, color: WHITE } });
  s.addText("Floods change nothing in the process, so only the flow monitor sees them. The stealth command is valid at the protocol level, so only the LSTM sees it. Replay re-sends the controller's most recent command, so only DPI sees it.",
    { x: M, y: 5.95, w: W - 2 * M, h: 0.9, fontFace: BODY, fontSize: 15, color: INK, margin: 0, valign: "top", isTextBox: true });
  pageNo(s, 11);
  s.addNotes("This grid is the detection-in-depth argument in one picture. Each layer has blind spots, and each blind spot is covered by another layer. Only the combined system reaches 100% on every attack class.");

  // 12 --------------------------------------------------------- HAI
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Reality check: the public HAI dataset", "Same LSTM on a real hardware-in-the-loop testbed: 7 attacks in 24 h (~1% of the time)");
  const rounds = [
    ["Round 1", "Trained on 1 recording (26 h)", [["0.74", "ROC-AUC: ranks attacks above normal"], ["91%", "of the test day flagged: unusable"]]],
    ["Round 2", "Trained on 3 recordings (117 h), threshold from a 4th", [["0.1%", "false-positive rate"], ["2 / 7", "attacks detected"]]],
  ];
  for (let i = 0; i < 2; i++) {
    const y = 1.85 + i * 2.5;
    card(s, M, y, 5.3, 2.25, i === 0 ? CARD : RED_LT);
    s.addText([{ text: rounds[i][0], options: { bold: true, color: INK, fontSize: 17, breakLine: true } },
      { text: rounds[i][1], options: { color: MUTED, fontSize: 12 } }],
    { x: M + 0.25, y: y + 0.15, w: 4.9, h: 0.75, fontFace: BODY, margin: 0, valign: "top", isTextBox: true });
    for (let j = 0; j < 2; j++) {
      s.addText([{ text: rounds[i][2][j][0], options: { fontSize: 28, bold: true, color: j === 1 && i === 0 ? RED : TEAL, breakLine: true } },
        { text: rounds[i][2][j][1], options: { fontSize: 11, color: INK } }],
      { x: M + 0.25 + j * 2.5, y: y + 0.95, w: 2.35, h: 1.2, fontFace: BODY, margin: 0, valign: "top", isTextBox: true });
    }
  }
  fitImage(s, "eval/results/hai_timeline_multiday.png", 6.2, 1.85, 6.53, 3.5);
  s.addText("The score follows a change of operating mode at ~16.8 h, not the attacks (red bands). That mode appears in none of the training recordings.",
    { x: 6.2, y: 5.45, w: 6.53, h: 1.0, fontFace: BODY, fontSize: 14, color: INK, margin: 0, valign: "top", isTextBox: true });
  pageNo(s, 12);
  s.addNotes("To check whether the LSTM generalises, we trained and tested it on HAI 22.04, data from a real hardware-in-the-loop testbed. It ranks attacks above normal better than chance, but it is not a usable alarm. With the threshold from training it flags most of the day; with the threshold set on a separate normal recording, false alarms are rare but it catches only 2 of 7 attacks. The plot shows why: the score tracks the plant's operating mode, which changes during the test day in a way the model never saw. We planned both rounds in advance and ran each once, so we did not tune the model to the test data.");

  // 13 --------------------------------------------------------- lessons
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "What we learned");
  const lessons = [
    ["FaRandom", "Operating modes break the LSTM", "A real plant switches modes between recordings. The model mistakes an unfamiliar normal mode for an attack; normalising within each mode is the next step."],
    ["FaFlask", "Simulation choices can fail on real data", "Scoring by the worst signal was essential for the stealth attack in simulation but was fragile on HAI's noisy sensors, where plain error did better."],
    ["FaBug", "Plot the data before trusting results", "A plot revealed that our controller never restored a pump after an attack. Fixing it changed every simulator result, and a test now guards it."],
  ];
  for (let i = 0; i < 3; i++) {
    const cx = M + i * 4.1, cy = 1.5;
    card(s, cx, cy, 3.85, 4.75);
    await circleIcon(s, lessons[i][0], cx + 0.3, cy + 0.35, 0.85, i === 2 ? RED : TEAL);
    s.addText(lessons[i][1], { x: cx + 0.3, y: cy + 1.4, w: 3.25, h: 0.95, fontFace: BODY, fontSize: 18, bold: true, color: INK, margin: 0, valign: "top", isTextBox: true });
    s.addText(lessons[i][2], { x: cx + 0.3, y: cy + 2.4, w: 3.25, h: 2.2, fontFace: BODY, fontSize: 16, color: MUTED, margin: 0, valign: "top", isTextBox: true });
  }
  pageNo(s, 13);
  s.addNotes("Three lessons. First, operating-mode changes are the main obstacle for the learning-based layer. Second, a design choice that works in a clean simulation can fail on real data. Third, plotting our own dataset revealed a bug in the simulated controller that had skewed our results; we fixed it, re-ran everything, and added a test so it cannot come back.");

  // 14 --------------------------------------------------------- limitations + future work
  s = pres.addSlide(); s.background = { color: WHITE };
  title(s, "Limitations and future work");
  card(s, M, 1.4, 5.85, 5.3);
  s.addText("Limitations", { x: M + 0.3, y: 1.6, w: 5.2, h: 0.5, fontFace: BODY, fontSize: 20, bold: true, color: RED, margin: 0, isTextBox: true });
  s.addText(bullets([
    "Simulator results are optimistic: one 510 s run, attacks we designed",
    "The LSTM does not generalise to HAI",
    "Network log is generator-recorded, not a packet capture",
    "Detection runs offline over recorded logs",
    "Hash chain on one host; Fabric and OpenPLC not integrated",
  ], { paraSpaceAfter: 14 }), { x: M + 0.3, y: 2.25, w: 5.3, h: 4.3, fontFace: BODY, fontSize: 18, color: INK, valign: "top", margin: 0, isTextBox: true });
  card(s, 6.88, 1.4, 5.85, 5.3, TEAL_LT);
  s.addText("Future work", { x: 7.18, y: 1.6, w: 5.2, h: 0.5, fontFace: BODY, fontSize: 20, bold: true, color: TEAL, margin: 0, isTextBox: true });
  s.addText(bullets([
    "Mode-aware normalisation or a rolling baseline for the LSTM",
    "Train on all six HAI recordings; confirm on test2 with eTaPR",
    "Capture traffic with tshark; add an EtherNet/IP decoder",
    "Run the detectors as live services behind the dashboard",
    "Hyperledger Fabric backend; OpenPLC in the loop",
  ], { paraSpaceAfter: 14 }), { x: 7.18, y: 2.25, w: 5.3, h: 4.3, fontFace: BODY, fontSize: 18, color: INK, valign: "top", margin: 0, isTextBox: true });
  pageNo(s, 14);
  s.addNotes("We want to be clear about the limits. The simulator results come from attacks we designed, the LSTM does not yet generalise to a real plant, the network log is recorded by our generator rather than captured from the wire, and detection runs offline. The future work follows directly from these: make the LSTM mode-aware, validate more widely on HAI, capture real traffic, and run the detectors live.");

  // 15 --------------------------------------------------------- conclusion
  s = pres.addSlide(); s.background = { color: NAVY };
  s.addText("Conclusion", { x: M, y: 0.7, w: 8, h: 0.8, fontFace: HEAD, fontSize: 36, bold: true, color: WHITE, margin: 0, isTextBox: true });
  const concl = [
    ["FaShieldAlt", "Layered detection works in simulation: all five attacks caught in the first second, with interpretable alerts."],
    ["FaLock", "A signed hash chain makes every command and alert tamper-evident."],
    ["FaChartLine", "On real data the LSTM is not yet reliable; handling operating modes is the key next step."],
  ];
  for (let i = 0; i < 3; i++) {
    const y = 1.85 + i * 1.3;
    await circleIcon(s, concl[i][0], M, y, 0.8, i === 2 ? RED : TEAL);
    s.addText(concl[i][1], { x: M + 1.1, y, w: 7.3, h: 0.8, fontFace: BODY, fontSize: 18, color: WHITE, valign: "middle", margin: 0, isTextBox: true });
  }
  s.addText("Thank you", { x: 9.2, y: 2.3, w: 3.5, h: 0.9, fontFace: HEAD, fontSize: 36, bold: true, color: MINT, align: "right", margin: 0, isTextBox: true });
  s.addText("Questions?", { x: 9.2, y: 3.2, w: 3.5, h: 0.6, fontFace: BODY, fontSize: 22, color: "C9D6E3", align: "right", margin: 0, isTextBox: true });
  s.addText("Code, results and report: private GitHub repository fyp-ics-water-treatment",
    { x: M, y: 6.3, w: 11, h: 0.4, fontFace: BODY, fontSize: 12, color: "9FB3C8", margin: 0, isTextBox: true });
  pageNo(s, 15, true);
  s.addNotes("To conclude: layered detection works on our simulated plant, catching all five attacks in the first second with alerts an operator can act on. The ledger makes the record tamper-evident. On real data the learning-based layer is not yet reliable, and handling operating modes is the next step. Thank you, we are happy to take questions or show the live demo.");

  await pres.writeFile({ fileName: OUT });
  console.log("wrote", OUT);
}
build().catch((e) => { console.error(e); process.exit(1); });
