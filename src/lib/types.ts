export type MediaSource = {
  name: string;
  category: string;
  url: string;
};

export type NewsSourceHit = {
  source: string;
  url: string;
};

export type CandidateArticle = {
  title: string;
  url: string;
  source: string;
  date: string;
  text: string;
};

export type NewsCard = {
  id: string;
  title: string;
  date: string;
  summary: string;
  sources: NewsSourceHit[];
  primaryUrl: string;
};

export type CrawlResponse = {
  generatedAt: string;
  window: {
    today: string;
    yesterday: string;
  };
  cards: NewsCard[];
};
