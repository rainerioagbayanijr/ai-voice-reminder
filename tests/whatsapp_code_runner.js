// Execute only repository-owned Code node sources, with explicit n8n input stubs.
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
Date.now = () => input.now;
const source = fs.readFileSync(input.script, 'utf8');
const $ = name => {
  if (name !== 'Validate Demo Setup') throw new Error('Unexpected node lookup');
  return { item: { json: input.config || {} } };
};
try {
  const result = new Function('$json', '$', '$binary', source)(input.json, $, {});
  process.stdout.write(JSON.stringify({ result }));
} catch (error) {
  process.stdout.write(JSON.stringify({ error: error.message }));
}
