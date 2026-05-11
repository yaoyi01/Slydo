using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace SlydoAddIn.Services
{
    public class RecommendResponse
    {
        [JsonProperty("results")]
        public List<SlideResult> Results { get; set; } = new List<SlideResult>();

        [JsonProperty("query")]
        public QueryInfo Query { get; set; }

        /// <summary>客户端侧错误信息（非后端返回）</summary>
        [JsonIgnore]
        public string RequestError { get; set; }

        /// <summary>是否来自离线缓存</summary>
        [JsonIgnore]
        public bool _isCached { get; set; }
    }

    public class SlideResult
    {
        [JsonProperty("slide_id")]
        public string SlideId { get; set; }

        /// <summary>映射后端 title 字段作为卡片标题</summary>
        [JsonProperty("title")]
        public string DeckName { get; set; }

        [JsonProperty("slide_index")]
        public int SlideIndex { get; set; }

        /// <summary>映射后端 reason 作为摘要</summary>
        [JsonProperty("reason")]
        public string Summary { get; set; }

        [JsonProperty("score")]
        public double Score { get; set; }

        [JsonProperty("llm_score")]
        public int LlmScore { get; set; }

        public string ThumbnailUrl { get; set; }
    }

    public class QueryInfo
    {
        [JsonProperty("title")]
        public string Original { get; set; }

        [JsonProperty("keywords")]
        public string Enriched { get; set; }

        public string[] Keywords { get; set; }
    }

    public class ExportRequest
    {
        public string SlideId { get; set; }
        public int TargetIndex { get; set; }
    }

    // ═══════════════════════════════════════════════════════════
    // 场景 B — 大纲推荐
    // ═══════════════════════════════════════════════════════════

    /// <summary>
    /// 大纲推荐响应
    /// </summary>
    public class OutlineResponse
    {
        [JsonProperty("directions")]
        public List<OutlineDirection> Directions { get; set; } = new List<OutlineDirection>();

        [JsonProperty("completed_titles")]
        public List<string> CompletedTitles { get; set; } = new List<string>();

        [JsonProperty("current_title")]
        public string CurrentTitle { get; set; }

        /// <summary>客户端侧错误信息（非后端返回）</summary>
        [JsonIgnore]
        public string Error { get; set; }

        /// <summary>是否来自离线缓存</summary>
        [JsonIgnore]
        public bool _isCached { get; set; }
    }

    /// <summary>
    /// 单个大纲走向
    /// </summary>
    public class OutlineDirection
    {
        [JsonProperty("direction")]
        public string Direction { get; set; }

        [JsonProperty("keywords")]
        public List<string> Keywords { get; set; } = new List<string>();

        [JsonProperty("reason")]
        public string Reason { get; set; }

        [JsonProperty("slide_count")]
        public int SlideCount { get; set; }

        [JsonProperty("slides")]
        public List<SlideResult> Slides { get; set; } = new List<SlideResult>();
    }

    // ═══════════════════════════════════════════════════════════
    // 离线缓存
    // ═══════════════════════════════════════════════════════════

    /// <summary>推荐结果缓存</summary>
    public class RecommendCache
    {
        [JsonProperty("data")]
        public RecommendResponse Data { get; set; }

        [JsonProperty("cached_at")]
        public DateTime CachedAt { get; set; }
    }

    /// <summary>大纲结果缓存</summary>
    public class OutlineCache
    {
        [JsonProperty("data")]
        public OutlineResponse Data { get; set; }

        [JsonProperty("cached_at")]
        public DateTime CachedAt { get; set; }
    }
}
