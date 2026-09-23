import { CSVData } from '../types';

function detectDelimiter(text: string): string {
  const firstLine = text.split(/\r?\n/, 1)[0] || '';
  const candidates = [',', ';', '\t', '|'];
  return candidates.reduce((best, candidate) =>
    firstLine.split(candidate).length > firstLine.split(best).length ? candidate : best,
  );
}

export async function readCsv(file: File): Promise<CSVData> {
  const bytes = await file.arrayBuffer();
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    text = new TextDecoder('windows-1258').decode(bytes);
  }
  text = text.replace(/^\uFEFF/, '');
  const delimiter = detectDelimiter(text);
  const parsed: string[][] = [];
  let row: string[] = [];
  let value = '';
  let quoted = false;

  for (let index = 0; index < text.length; index++) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        value += '"';
        index++;
      } else {
        quoted = !quoted;
      }
    } else if (character === delimiter && !quoted) {
      row.push(value.trim());
      value = '';
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && text[index + 1] === '\n') index++;
      row.push(value.trim());
      if (row.some((cell) => cell)) parsed.push(row);
      row = [];
      value = '';
    } else {
      value += character;
    }
  }
  row.push(value.trim());
  if (row.some((cell) => cell)) parsed.push(row);
  if (parsed.length < 2) throw new Error('CSV needs a header and at least one product row.');

  const headers = parsed[0];
  return {
    headers,
    rows: parsed.slice(1).map((cells) => Object.fromEntries(
      headers.map((header, index) => [header, cells[index] ?? '']),
    )),
  };
}
