'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const commands = require(path.join(__dirname, '../static/codex-commands.js'));

const expectedVisibleCommands = [
  '/model', '/fast', '/ide', '/permissions', '/keymap', '/vim', '/experimental', '/approve',
  '/memories', '/skills', '/import', '/hooks', '/review', '/rename', '/new', '/archive',
  '/delete', '/resume', '/fork', '/init', '/compact', '/plan', '/goal', '/agent', '/side',
  '/copy', '/export', '/raw', '/diff', '/mention', '/status', '/usage', '/title', '/statusline',
  '/theme', '/pets', '/mcp', '/plugins', '/logout', '/exit', '/feedback', '/ps', '/stop',
  '/clear', '/personality', '/subagents',
];

assert.equal(commands.testedCodexVersion, '0.148.0');
assert.deepEqual(commands.inventory.map((entry) => entry.command), expectedVisibleCommands);
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../static/codex-command-catalog.json'), 'utf8'));
assert.deepEqual(catalog.commands.map((entry) => entry.command), expectedVisibleCommands);
assert.equal(new Set(expectedVisibleCommands).size, expectedVisibleCommands.length);
assert.equal(commands.match('/').length, expectedVisibleCommands.length);

const rename = commands.match('/ren')[0];
assert.equal(rename.command, '/rename');
assert.equal(rename.value, '/rename ');
assert.equal(rename.argumentHint, '<name>');

const sideAlias = commands.match('/bt')[0];
assert.equal(sideAlias.command, '/side');
assert.equal(sideAlias.matchedAlias, '/btw');
assert.equal(sideAlias.value, '/btw');

assert.equal(commands.match('/prsnlty')[0].command, '/personality');
assert.equal(commands.match('/syntax')[0].command, '/theme');
assert.equal(commands.match('/model').length, 0);

const directories = commands.match('cd ~/p', { recentDirectories: ['cd ~/project', 'cd ~/notes'] });
assert.deepEqual(directories.map((entry) => entry.value), ['cd ~/project']);

const launches = commands.match('codex ');
assert.ok(launches.some((entry) => entry.value === 'codex resume'));
assert.ok(launches.every((entry) => !entry.value.includes('yolo')));

assert.equal(commands.inventory.find((entry) => entry.command === '/delete').risk, 'destructive');
assert.equal(commands.inventory.find((entry) => entry.command === '/feedback').risk, 'sends logs');

assert.equal(commands.replaceInventory([
  { command: '/model', description: 'Runtime model', behavior: 'menu' },
  { command: '/future-command', description: 'Future command', behavior: 'unclassified' },
], { observedCodexVersion: '0.149.0', drifted: true }), true);
assert.deepEqual(commands.inventory.map((entry) => entry.command), ['/model', '/future-command']);
assert.equal(commands.match('/future')[0].command, '/future-command');
assert.equal(commands.inventory[1].risk, 'unclassified');
assert.equal(commands.catalogDrifted, true);
assert.equal(commands.replaceInventory(catalog.commands, { observedCodexVersion: catalog.testedCodexVersion, drifted: false }), true);
assert.equal(commands.inventory.length, expectedVisibleCommands.length);

console.log(`codex command inventory tests passed (${commands.inventory.length} visible commands)`);
