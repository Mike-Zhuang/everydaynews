import * as cheerio from "cheerio";
import { MEDIA_SOURCES } from "@/lib/mediaSources";
import type { CandidateArticle, NewsCard } from "@/lib/types";

type OpenAIArticle = {
  section?: "产业动向" | "宏观地缘";
  title: string;
  date: string;
  summary: string;
  source: string;
  url: string;
  canonicalKey: string;
};

const REQUEST_TIMEOUT_MS = 3500;
const MAX_LINKS_PER_SOURCE = 4;
const MAX_ARTICLES_PER_SOURCE = 3;
const MAX_CANDIDATES_FOR_OPENAI = 24;
const DEFAULT_OPENAI_BASE_URL = "https://api.gptoai.top";
const DEFAULT_OPENAI_MODEL = "gpt-5.4";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36";

type UnionSearchResult = {
  title: string;
  url: string;
  snippet: string;
  platform: string;
};

const allowedSourceHosts = MEDIA_SOURCES.map((source) => {
  try {
    return new URL(source.url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}).filter(Boolean);

const sourceNameByHost = new Map(
  MEDIA_SOURCES.flatMap((source) => {
    try {
      const host = new URL(source.url).hostname.replace(/^www\./, "");
      return [[host, source.name] as const];
    } catch {
      return [];
    }
  })
);

export function dateKey(date: Date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

export function currentWindow() {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  return {
    today: dateKey(now),
    yesterday: dateKey(yesterday),
    valid: new Set([dateKey(now), dateKey(yesterday)])
  };
}

async function fetchHtml(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        "user-agent": USER_AGENT,
        accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8"
      },
      redirect: "follow"
    });

    if (!response.ok) return null;
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("text/html") && !contentType.includes("application/xhtml+xml")) {
      return null;
    }

    return response.text();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function normalizeUrl(href: string, baseUrl: string) {
  try {
    const resolved = new URL(href, baseUrl);
    if (!["http:", "https:"].includes(resolved.protocol)) return null;
    resolved.hash = "";
    return resolved.toString();
  } catch {
    return null;
  }
}

function isUsableArticleUrl(url: string) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "");
    if (!["http:", "https:"].includes(parsed.protocol)) return false;
    if (/\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3)$/i.test(parsed.pathname)) return false;
    if (/google|bing|duckduckgo|baidu|sogou|so\.com|javascript/i.test(parsed.hostname)) return false;
    return allowedSourceHosts.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
  } catch {
    return false;
  }
}

function sourceNameForUrl(url: string, fallback: string) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    const matched = allowedSourceHosts.find((allowed) => host === allowed || host.endsWith(`.${allowed}`));
    return matched ? (sourceNameByHost.get(matched) ?? fallback) : fallback;
  } catch {
    return fallback;
  }
}

function extractMediaPageLinks(html: string, baseUrl: string, source: string) {
  const $ = cheerio.load(html);
  const links: UnionSearchResult[] = [];
  const seen = new Set<string>();

  $("a[href]").each((_, element) => {
    const href = $(element).attr("href");
    const title = $(element).text().replace(/\s+/g, " ").trim();
    if (!href || title.length < 6) return;
    const url = normalizeUrl(href, baseUrl);
    if (!url || seen.has(url) || !isUsableArticleUrl(url)) return;
    seen.add(url);
    links.push({ title, url, snippet: "", platform: source });
  });

  return links.slice(0, MAX_LINKS_PER_SOURCE);
}

function parseDate(raw?: string | null) {
  if (!raw) return null;
  const clean = raw.replace(/\s+/g, " ").trim();
  const isoMatch = clean.match(/20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}/);
  if (!isoMatch) return null;
  const normalized = isoMatch[0].replace(/[年月/.]/g, "-").replace(/日/g, "");
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;
  return dateKey(parsed);
}

function extractArticle(html: string, fallbackTitle: string, url: string, source: string) {
  const $ = cheerio.load(html);
  $("script, style, noscript, nav, footer, header, aside").remove();

  const title =
    $("meta[property='og:title']").attr("content") ||
    $("h1").first().text() ||
    $("title").text() ||
    fallbackTitle;

  const date =
    parseDate($("meta[property='article:published_time']").attr("content")) ||
    parseDate($("meta[name='pubdate']").attr("content")) ||
    parseDate($("meta[name='publishdate']").attr("content")) ||
    parseDate($("time[datetime]").first().attr("datetime")) ||
    parseDate($("time").first().text()) ||
    parseDate($.root().text()) ||
    dateKey(new Date());

  const paragraphs = $("article p, main p, .article p, .content p, .post p, p")
    .map((_, p) => $(p).text().replace(/\s+/g, " ").trim())
    .get()
    .filter((line) => line.length > 20);

  const text = paragraphs.join("\n").slice(0, 3500);

  if (!date || text.length < 80) return null;

  return {
    title: title.replace(/\s+/g, " ").trim().slice(0, 180),
    url,
    source,
    date,
    text
  } satisfies CandidateArticle;
}

async function mapConcurrent<T, R>(
  items: T[],
  limit: number,
  mapper: (item: T) => Promise<R>
) {
  const results: R[] = [];
  let index = 0;

  async function worker() {
    while (index < items.length) {
      const current = items[index++];
      results.push(await mapper(current));
    }
  }

  await Promise.all(Array.from({ length: limit }, worker));
  return results;
}

export async function collectCandidates(validDates: Set<string>) {
  const candidates: CandidateArticle[] = [];

  for (const source of MEDIA_SOURCES) {
    const articles = await collectCandidatesFromSource(source.url, source.name, validDates);
    candidates.push(...articles);
    if (candidates.length >= MAX_CANDIDATES_FOR_OPENAI) break;
  }

  return candidates.slice(0, MAX_CANDIDATES_FOR_OPENAI);
}

export async function collectCandidatesFromSource(sourceUrl: string, sourceName: string, validDates: Set<string>) {
  const html = await fetchHtml(sourceUrl);
  if (!html) return [];

  const links = extractMediaPageLinks(html, sourceUrl, sourceName);
  const articles = await mapConcurrent(links, 3, async (link) => {
    const html = await fetchHtml(link.url);
    if (!html) return null;
    const article = extractArticle(html, link.title, link.url, sourceNameForUrl(link.url, sourceName));
    if (!article || !validDates.has(article.date)) return null;
    return article;
  });

  return (articles.filter(Boolean) as CandidateArticle[]).slice(0, MAX_ARTICLES_PER_SOURCE);
}

export function candidatesToCards(candidates: CandidateArticle[]): NewsCard[] {
  return candidates.map((article) => ({
    id: article.url,
    title: article.title,
    date: article.date,
    summary: article.text.slice(0, 220),
    sources: [{ source: article.source, url: article.url }],
    primaryUrl: article.url
  }));
}

function parseOpenAIJson(text: string) {
  const fenced = text.match(/```json\s*([\s\S]*?)```/i);
  const body = fenced?.[1] ?? text;
  const firstArrayStart = body.indexOf("[");
  const firstObjectStart = body.indexOf("{");
  const lastArrayEnd = body.lastIndexOf("]");
  const lastObjectEnd = body.lastIndexOf("}");
  const jsonText =
    firstArrayStart !== -1 && lastArrayEnd !== -1
      ? body.slice(firstArrayStart, lastArrayEnd + 1)
      : firstObjectStart !== -1 && lastObjectEnd !== -1
        ? body.slice(firstObjectStart, lastObjectEnd + 1)
        : body;

  try {
    const parsed = JSON.parse(jsonText);
    if (Array.isArray(parsed)) return parsed as OpenAIArticle[];
    if (Array.isArray(parsed.articles)) return parsed.articles as OpenAIArticle[];
    return [];
  } catch {
    throw new Error(`Model did not return valid JSON: ${clipText(body)}`);
  }
}

function clipText(value: string, maxLength = 400) {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length > maxLength ? `${clean.slice(0, maxLength)}...` : clean;
}

function parseMaybeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function mergeArticles(articles: OpenAIArticle[]): NewsCard[] {
  const groups = new Map<string, NewsCard>();

  for (const article of articles) {
    const key = (article.canonicalKey || article.title).toLowerCase().trim();
    const existing = groups.get(key);
    const sourceHit = { source: article.source, url: article.url };

    if (!existing) {
      groups.set(key, {
        id: key.replace(/[^a-z0-9\u4e00-\u9fa5]+/gi, "-").slice(0, 80),
        section: article.section,
        title: article.title,
        date: article.date,
        summary: article.summary,
        sources: [sourceHit],
        primaryUrl: article.url
      });
      continue;
    }

    if (article.date > existing.date) existing.date = article.date;
    if (!existing.sources.some((item) => item.url === article.url)) {
      existing.sources.push(sourceHit);
    }
  }

  return Array.from(groups.values()).sort((a, b) => b.date.localeCompare(a.date));
}

export async function summarizeWithOpenAI(candidates: CandidateArticle[], keywords: string[]) {
  if (candidates.length === 0) return [];

  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("Missing OPENAI_API_KEY. Add it to .env.local before crawling.");
  }

  const baseUrl = (process.env.OPENAI_BASE_URL?.trim() || DEFAULT_OPENAI_BASE_URL).replace(/\/$/, "");
  const model = process.env.OPENAI_MODEL?.trim() || DEFAULT_OPENAI_MODEL;
  const prompt = `
你是中文新闻编辑。请从候选新闻中筛选和这些关键词/主题相关的内容：${keywords.join("、")}。
请严格按照以下选题规则筛选：
1. 优先选取官方机构、权威媒体及大型正规媒体的报道，不使用未经证实或来源不明的消息，尽可能不用证券网站。
2. 文旅、医疗及地方相关事宜不选；涉及外国和台湾的内容尽量不选，除非与中国宏观经济、产业链或地缘关系直接相关。
3. 避免日常外事活动和口号宣誓类内容，立场保持中立。地缘板块不选出访或外事接待内容。
4. 每日报告的信息来源中必须尽量包含至少一条外媒报道。
5. 不选尚未发生的事件，不得选择分析或评论文章；只选已经发生、有事实增量的报道。
6. 宏观经济方面尽量选取一条涉房地产内容，最终落脚点必须是对我国宏观经济的影响。
7. 外国企业或对中国产业动态无直接影响的不予选择。
8. 地缘新闻必须包括中国和另外国家。国家优先级：美国、日本、俄罗斯、欧洲、印度；以中美关系为主，无合适新闻再选中日、欧洲、澳大利亚、印度。
9. 每则新闻最好使用两条来源交叉印证；如果候选中有同一事件的多源报道，请合并为一则。
10. 选题需体现产业发展的关键进展、技术迭代或商业模式重要变化，避免价值有限的日常信息；半导体等板块关注我国龙头企业进展。
11. 宏观经济可选择荣鼎、摩根士丹利、高盛、达沃斯等国际知名智库、组织对我国宏观经济的分析或预测。

输出模仿日报格式，分为“产业动向”和“宏观地缘”两组。每则新闻 summary 写成 3 个自然段：
第一段：事实，含日期、主体、事件和关键数据；
第二段：背景或原因；
第三段：对我国产业、宏观经济或地缘格局的影响判断，保持中立。
每则新闻尽量保留 2 条来源；如果只有 1 条可靠来源，也可以保留。
如果多篇文章报道同一事件，给它们完全相同的 canonicalKey，并合并来源。
只返回 JSON 数组，不要返回解释文字，不要 Markdown 代码块。数组元素格式：
{
  "section": "产业动向 或 宏观地缘",
  "title": "标题",
  "date": "YYYY-MM-DD",
  "summary": "内容要点概括",
  "source": "新闻来源",
  "url": "新闻链接",
  "canonicalKey": "同一新闻事件的稳定短键"
}

候选新闻：
${JSON.stringify(
  candidates.map((item) => ({
    title: item.title,
    date: item.date,
    source: item.source,
    url: item.url,
    text: item.text
  }))
)}
`;

  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "User-Agent": "Apifox/1.0.0 (https://apifox.com)"
    },
    body: JSON.stringify({
      model,
      messages: [
        {
          role: "system",
          content: "You are a precise Chinese news editor. Return valid JSON only."
        },
        {
          role: "user",
          content: prompt
        }
      ]
    })
  });

  const rawResponse = await response.text();
  const data = parseMaybeJson(rawResponse);
  if (!response.ok) {
    const message =
      data?.error?.message ??
      data?.message ??
      clipText(rawResponse) ??
      `OpenAI-compatible API request failed: ${response.status}`;
    throw new Error(`OpenAI-compatible API request failed: ${message}`);
  }
  if (!data) {
    throw new Error(`OpenAI-compatible API returned non-JSON response: ${clipText(rawResponse)}`);
  }

  const text = data?.choices?.[0]?.message?.content;
  if (typeof text !== "string") {
    throw new Error("OpenAI-compatible API returned an empty response.");
  }

  return parseOpenAIJson(text);
}
