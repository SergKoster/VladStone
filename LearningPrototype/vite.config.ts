import { readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const prototypeRoot = fileURLToPath(new URL(".", import.meta.url));
const courseRoot = resolve(prototypeRoot, "../docs/learning/course");
const ankiPath = resolve(prototypeRoot, "../docs/learning/anki/vladstone-gl1-2.txt");
const progressPath = resolve(prototypeRoot, "data/learning-progress.json");

type CourseChapter = {
  id: string;
  title: string;
  sourcePath: string;
  body: string;
  cards: {
    id: string;
    prompt: string;
    expectedAnswer: string;
    tag: string;
    chapterId: string;
  }[];
};

function numberedItems(text: string) {
  return text
    .trim()
    .split(/\r?\n(?=\d+\.\s+)/)
    .map((item) => item.replace(/^\d+\.\s+/, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function extractSelfCheckCards(chapterId: string, body: string) {
  const section = body.match(
    /^#{2,3}\s+Самопроверка[^\n]*\n([\s\S]*?)\n<details>\s*\n<summary>[^<]*ответ[^<]*<\/summary>\s*\n([\s\S]*?)<\/details>/im,
  );
  if (!section) return [];

  const prompts = numberedItems(section[1]);
  const expectedAnswers = numberedItems(section[2]);
  return prompts
    .map((prompt, index) => ({
      id: `chapter-${chapterId}-${index + 1}`,
      prompt,
      expectedAnswer: expectedAnswers[index] ?? "Сверь ответ с материалом главы и назови первую ошибочную предпосылку.",
      tag: `chapter-${chapterId}`,
      chapterId,
    }))
    .filter((card) => Boolean(card.expectedAnswer));
}

async function readCourse(): Promise<CourseChapter[]> {
  const files = (await readdir(courseRoot))
    .filter((file) => /^\d{2}-.+\.md$/.test(file) && file !== "00-ai-tutor-contract.md")
    .sort();

  return Promise.all(
    files.map(async (file) => {
      const body = await readFile(resolve(courseRoot, file), "utf8");
      const title = body.match(/^#\s+(.+)$/m)?.[1] ?? file;
      return {
        id: file.slice(0, 2),
        title,
        sourcePath: `docs/learning/course/${file}`,
        body,
        cards: extractSelfCheckCards(file.slice(0, 2), body),
      };
    }),
  );
}

async function readAnki() {
  const text = await readFile(ankiPath, "utf8");
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line, index) => {
      const [prompt, expectedAnswer, tag = "review"] = line.split("\t");
      const chapterId = tag === "gl1" ? "01" : "02";
      return { id: `anki-${index + 1}`, prompt, expectedAnswer, tag, chapterId };
    });
}

function localLearningApi(): Plugin {
  return {
    name: "local-learning-api",
    configureServer(server) {
      server.middlewares.use("/api/bootstrap", async (_request, response) => {
        try {
          const [chapters, ankiCards] = await Promise.all([readCourse(), readAnki()]);
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.end(JSON.stringify({ chapters, ankiCards }));
        } catch (error) {
          response.statusCode = 500;
          response.end(JSON.stringify({ error: String(error) }));
        }
      });

      server.middlewares.use("/api/progress", async (request, response) => {
        if (request.method === "GET") {
          try {
            const saved = await readFile(progressPath, "utf8");
            response.setHeader("Content-Type", "application/json; charset=utf-8");
            response.end(saved);
          } catch {
            response.statusCode = 204;
            response.end();
          }
          return;
        }

        if (request.method !== "POST") {
          response.statusCode = 405;
          response.end();
          return;
        }

        let body = "";
        request.on("data", (chunk) => {
          body += chunk;
        });
        request.on("end", async () => {
          try {
            const progress = JSON.parse(body);
            await mkdir(resolve(prototypeRoot, "data"), { recursive: true });
            await writeFile(progressPath, `${JSON.stringify(progress, null, 2)}\n`, "utf8");
            response.statusCode = 204;
            response.end();
          } catch {
            response.statusCode = 400;
            response.end("Invalid learning progress");
          }
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), localLearningApi()],
});
