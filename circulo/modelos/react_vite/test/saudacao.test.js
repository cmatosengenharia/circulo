import assert from 'node:assert/strict'
import { test } from 'node:test'
import { NOME, saudacao } from '../src/saudacao.js'

test('saudacao', () => assert.equal(saudacao('ana'), `${NOME}: olá, ana`))
