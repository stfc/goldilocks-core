import { Accordion } from "@mantine/core";

import type { ComputationResult } from "../api/coreClient";
import { ScientificRecord } from "./ScientificRecord";

export function RecordReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const records = Object.entries(result.records);
  return (
    <section className="review-section record-review">
      <header>
        <span className="review-section__index">D</span>
        <div>
          <h3>Scientific records</h3>
          <p>{records.length} records</p>
        </div>
      </header>
      <Accordion
        multiple
        order={4}
        chevron={
          <span className="review-disclosure__glyph" aria-hidden="true" />
        }
        disableChevronRotation
        classNames={{
          root: "record-list",
          item: "record-card",
          control: "review-disclosure__control record-card__control",
          label: "review-disclosure__label record-card__label",
          chevron: "review-disclosure__indicator",
          content: "review-disclosure__content",
        }}
      >
        {records.map(([name, value]) => (
          <Accordion.Item key={name} value={name}>
            <Accordion.Control>
              <span>{readableName(name)}</span>
              <code className="record-card__key">{name}</code>
            </Accordion.Control>
            <Accordion.Panel>
              <ScientificRecord
                name={name as keyof ComputationResult["records"]}
                result={result}
              />
              <Accordion
                order={5}
                chevron={
                  <span
                    className="review-disclosure__glyph"
                    aria-hidden="true"
                  />
                }
                disableChevronRotation
                classNames={{
                  root: "record-raw",
                  item: "review-disclosure__item",
                  control: "review-disclosure__control record-raw__control",
                  label: "review-disclosure__label record-raw__label",
                  chevron: "review-disclosure__indicator",
                  content: "review-disclosure__content",
                }}
              >
                <Accordion.Item value="json">
                  <Accordion.Control>
                    Raw {readableName(name)} record (JSON)
                  </Accordion.Control>
                  <Accordion.Panel>
                    <pre
                      role="region"
                      className="record-json"
                      tabIndex={0}
                      aria-label={`Raw ${readableName(name)} record`}
                    >
                      {JSON.stringify(value, null, 2)}
                    </pre>
                  </Accordion.Panel>
                </Accordion.Item>
              </Accordion>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </section>
  );
}

function readableName(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
