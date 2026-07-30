export type CourseChapter = {
  id: string;
  title: string;
  sourcePath: string;
  body: string;
};

export type LearningCard = {
  id: string;
  prompt: string;
  expectedAnswer: string;
  tag: string;
  hint?: string;
  source: string;
};

export type Bootstrap = {
  chapters: CourseChapter[];
  cards: Omit<LearningCard, "source">[];
};

export type AnswerResult = "understood" | "review";

export type AnswerRecord = {
  questionId: string;
  prompt: string;
  source: string;
  answer: string;
  confidence: number;
  result: AnswerResult;
  hintsOpened: number;
  answeredAt: string;
};

export type LearningProgress = {
  version: 1;
  currentChapterId: string;
  preferredLength: 5 | 10 | 15;
  answers: AnswerRecord[];
  completedSessions: { completedAt: string; questionIds: string[] }[];
  updatedAt: string;
};
