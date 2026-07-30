export type LearningCard = {
  id: string;
  prompt: string;
  expectedAnswer: string;
  tag: string;
  chapterId: string;
  hint?: string;
  source: string;
  kind: "bridge" | "course" | "anki";
};

export type CourseChapter = {
  id: string;
  title: string;
  sourcePath: string;
  body: string;
  cards: Omit<LearningCard, "source" | "kind">[];
};

export type Bootstrap = {
  chapters: CourseChapter[];
  ankiCards: Omit<LearningCard, "source" | "kind">[];
};

export type SelfAssessment = "understood" | "review";

export type AnswerRecord = {
  questionId: string;
  prompt: string;
  source: string;
  answer: string;
  confidence: number;
  selfAssessment: SelfAssessment;
  hintsOpened: number;
  answeredAt: string;
};

export type CardSchedule = {
  level: number;
  dueAt: string;
  lastSelfAssessment: SelfAssessment;
  lastAnsweredAt: string;
};

export type LearningProgress = {
  version: 1;
  currentChapterId: string;
  preferredLength: 5 | 10 | 15;
  answers: AnswerRecord[];
  cardSchedules: Record<string, CardSchedule>;
  completedSessions: { completedAt: string; questionIds: string[] }[];
  updatedAt: string;
};
