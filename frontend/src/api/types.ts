export type MediaStatus = 'pending' | 'downloading' | 'transcribing' | 'translating' | 'ready' | 'error'

export interface Media {
  id: number
  kind: string
  source_url: string
  external_id: string
  title: string
  thumbnail: string
  duration: number
  status: MediaStatus
  progress: number
  error: string
  /** Every part of the audio has been turned into sentences. */
  transcribed: boolean
  /** Estimated difficulty, set once the transcript is ready ('' before then). */
  level: BookLevel | ''
  sentence_count: number
  translated_count: number
  /** How far into the audio the transcript reaches, in seconds. */
  covered_until: number
  /** Enough is ready to start studying even though processing goes on. */
  playable: boolean
  /** While waiting to be processed: how many jobs are ahead (0 when it is running or not waiting). */
  queue_position: number
}

export interface TimedWord {
  text: string
  start: number
  end: number
}

export interface Segment {
  id: number
  idx: number
  start: number
  end: number
  text: string
  translation: string
  words: TimedWord[]
}

export interface MediaDetail extends Media {
  segments: Segment[]
}

export interface Example {
  en: string
  zh: string
}

export interface WordPart {
  part: string
  meaning: string
}

export interface WordEnrichment {
  english_definition: string
  examples: Example[]
  prefix: WordPart
  root: WordPart
  suffix: WordPart
  synonyms: string[]
  antonyms: string[]
}

export interface WordResult {
  query: string
  found: boolean
  entry?: {
    word: string
    phonetic: string
    translation: string
    pos: string
    tags: string[]
    level: number
    level_label: string
    forms: Record<string, string>
    is_inflection: boolean
  }
  /** the word to ask the AI about (the base form for an inflected word); the AI part is null until it has been made */
  target?: string
  ai: WordEnrichment | null
  ai_error: string | null
}

export interface RootResult {
  root: string
  words: { word: string; translation: string; level: number }[]
}

export interface SentenceExplanation {
  translation: string
  structure: string
  grammar_points: { point: string; explanation: string }[]
  phrases: { phrase: string; meaning: string }[]
  similar_examples: Example[]
}

export interface SavedPhrase {
  id: number
  text: string
  context_sentence: string
  translation: string
  note: string
  source_kind: string
  source_id: number | null
  timestamp: number
  created_at: string
}

/** What the streaming explain endpoint sends while the answer is still being written. */
export interface PartialExplanation {
  translation?: string
  structure?: string
  grammar_points?: Partial<{ point: string; explanation: string }>[]
  phrases?: Partial<{ phrase: string; meaning: string }>[]
  similar_examples?: Partial<Example>[]
}

export type TokenStatus = 'ok' | 'unclear' | 'wrong' | 'missing' | 'extra'

/** One word of the shadowing comparison, in reading order. */
export interface ShadowToken {
  text: string
  status: TokenStatus
  heard: string | null
}

export interface ShadowFeedback {
  summary: string
  tips: string[]
}

export interface ShadowRecording {
  id: number
  segment_id: number
  duration: number
  heard_text: string
  score: number
  tokens: ShadowToken[]
  feedback: ShadowFeedback | null
  created_at: string
}

export interface PartialFeedback {
  summary?: string
  tips?: string[]
}

/** What appeared since the page last asked (see GET /api/media/{id}/updates). */
export interface MediaUpdates extends Media {
  new_segments: Segment[]
  /** Translations by sentence index (as a string key) for sentences the page still lacked. */
  translations: Record<string, string>
}

export interface PodcastEpisode {
  title: string
  audio_url: string
  published: string
  duration: number
  summary: string
}

/** A podcast the learner follows. */
export interface PodcastChannel {
  id: number
  title: string
  url: string
  image: string
}

export interface PodcastShow {
  title: string
  image: string
  episodes: PodcastEpisode[]
}

/** What a pasted link turned out to be. */
export type PodcastLookup =
  | { type: 'audio'; audio_url: string }
  | { type: 'feed'; title: string; image: string; episodes: PodcastEpisode[] }

export type BookLevel = 'A2' | 'B1' | 'B2' | 'C1+'

export interface Book {
  id: number
  title: string
  author: string
  source: 'epub' | 'text' | 'gutenberg' | 'news'
  source_key: string
  cover: string
  /** For a news article: the original page, its date (YYYY-MM-DD) and the site. */
  url: string
  published: string
  site: string
  level: BookLevel | ''
  score: number
  word_count: number
  paragraph_count: number
  chapter_count: number
  last_chapter: number
  last_paragraph: number
  progress_percent: number
}

export interface ChapterInfo {
  idx: number
  title: string
  paragraph_count: number
  word_count: number
  /** Index (in the whole book) of this chapter's first paragraph. */
  first_paragraph: number
}

export interface BookDetail extends Book {
  chapters: ChapterInfo[]
}

export interface BookParagraph {
  id: number
  idx: number
  text: string
  translation: string
}

export interface BookChapter {
  idx: number
  title: string
  paragraphs: BookParagraph[]
}

export interface GutenbergResult {
  id: number
  title: string
  author: string
  cover: string
}

export interface NewsFeed {
  id: number
  title: string
  url: string
}

export interface FeedItem {
  title: string
  url: string
  published: string
  summary: string
  /** Set when the article has already been opened before. */
  article_id: number | null
  level: BookLevel | ''
}

export interface CloudPreset {
  id: string
  label: string
  base_url: string
  model: string
  note: string
}

export interface AppSettings {
  llm_model: string
  whisper_model: string
  llm_backend: 'ollama' | 'cloud'
  cloud_base_url: string
  cloud_model: string
  /** the API key is never sent to the page: only its last characters, or '' when there is none */
  cloud_key: string
  stt_backend: 'local' | 'cloud'
  stt_base_url: string
  stt_model: string
  stt_key: string
  /** When the cloud service fails, do the work on the local model instead. */
  fallback_local: boolean
  llm_presets: CloudPreset[]
  stt_presets: CloudPreset[]
  ollama_ok: boolean
  llm_models: { name: string; size_gb: number }[]
  whisper_models: { repo: string; label: string; size: string; note: string; downloaded: boolean }[]
}

export interface User {
  id: number
  username: string
  is_admin: boolean
}

export interface AdminUser extends User {
  disabled: boolean
  created_at: string
  usage_today: { media: number; audio_minutes: number; ai: number }
}

export interface FallbackCounts {
  today: number
  week: number
}

/** The daily limits, and how often the cloud service failed and the local model took over. */
export interface AdminUsage {
  limits: { media: number; audio_minutes: number; ai: number }
  fallbacks: { llm: FallbackCounts; stt: FallbackCounts }
  resets_at: string
}

export interface Invite {
  code: string
  state: 'open' | 'used' | 'expired'
  created_at: string
  expires_at: string
  used_by: string | null
}

export interface Health {
  ok: boolean
  llm_backend?: 'ollama' | 'cloud'
  stt_backend?: 'local' | 'cloud'
  cloud_configured?: boolean
  stt_configured?: boolean
  ollama: boolean
  llm_model: string
  llm_model_installed: boolean
  dict: boolean
  ffmpeg: boolean
}

export interface ReviewPhrase extends SavedPhrase {
  due_at: string
  interval_days: number
  ease: number
  reps: number
  lapses: number
}

export interface ReviewQueue {
  cards: ReviewPhrase[]
  due_count: number
  total: number
  next_due: string | null
}

/** The AI's word explanation while it is still being written: every part may be missing or unfinished. */
export interface PartialEnrichment {
  english_definition?: string
  examples?: Partial<Example>[]
  prefix?: Partial<WordPart>
  root?: Partial<WordPart>
  suffix?: Partial<WordPart>
  synonyms?: string[]
  antonyms?: string[]
}

export interface TtsStatus {
  available: boolean
  problems: string[]
  model_downloaded: boolean
  default_voice: string
  voices: { id: string; label: string }[]
}
