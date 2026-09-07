import { Accordion, Group } from "@mantine/core";

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
      <Group component="header" gap={12} wrap="nowrap" mb={16}>
        <span className="review-section__index">D</span>
        <div>
          <h3>Scientific records</h3>
          <p>{records.length} records</p>
        </div>
      </Group>
      <Accordion
        multiple
        order={4}
        chevron={<span aria-hidden="true" />}
        disableChevronRotation
        className="review-disclosure record-list"
        style={{ display: "grid", gap: 8 }}
      >
        {records.map(([name, value]) => (
          <Accordion.Item key={name} value={name} className="record-card">
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
                chevron={<span aria-hidden="true" />}
                disableChevronRotation
                className="review-disclosure record-raw"
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
