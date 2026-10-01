export interface AnalyticsOverview {
  total_media: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  recent_analytics?: Array<Record<string, unknown>>;
}

export interface TimeseriesItem {
  fetched_at: string;
  reach: number;
  impressions: number;
  likes: number;
  comments: number;
  saves: number;
}

export interface CategoryStat {
  count: number;
}
