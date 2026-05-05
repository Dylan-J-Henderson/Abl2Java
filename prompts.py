"""
prompts.py
──────────
All LLM system prompts used by ABL2Java.
Keeping them in one file makes tuning easy without touching logic code.

"""

# ── Shared ABL→Java construct mapping (injected into every prompt) ────────────
_CONSTRUCT_MAP = """\
ABL → Java construct mapping (apply all rules):

VARIABLES / FIELDS
  DEFINE VARIABLE x AS CHARACTER   → String x
  DEFINE VARIABLE x AS INTEGER     → int x  (or Integer for nullable)
  DEFINE VARIABLE x AS DECIMAL     → BigDecimal x
  DEFINE VARIABLE x AS LOGICAL     → boolean x
  DEFINE VARIABLE x AS DATE        → LocalDate x
  DEFINE VARIABLE x AS DATETIME    → LocalDateTime x

TEMP-TABLES
  DEFINE TEMP-TABLE with a PRIMARY UNIQUE index on exactly ONE DECIMAL /
  INTEGER field, used only for old→new object-ID remapping throughout the
  procedure  →  Map<BigDecimal,BigDecimal>  (e.g. HashMap<>()).
  Do NOT generate a record class for these lookup-map tables.
  Any other TEMP-TABLE  →  Java record or DTO inner class.

STRING OPERATIONS
  ENTRY(n, str, delim)  →  str.split(delim, -1)[n-1]
    ⚠  ABL ENTRY() is 1-based; Java arrays are 0-based — always subtract 1.
  CHR(31)               →  String.valueOf((char)31)   /* ASCII Unit Separator */
  CHR(n)                →  String.valueOf((char)n)
  TRIM(x)               →  x.trim()
  STRING(x)             →  String.valueOf(x)
  QUOTER(x)             →  "\"" + x + "\""  (or equivalent quoting helper)

STREAM / FILE I/O
  DEFINE STREAM s                          →  (declare BufferedReader field)
  INPUT STREAM s FROM VALUE(path)          →  new BufferedReader(new FileReader(path))
  IMPORT STREAM s UNFORMATTED variable     →  variable = reader.readLine()
  INPUT STREAM s CLOSE                     →  reader.close()  (prefer try-with-resources)

DATABASE OPERATIONS
  FIND FIRST <tbl> NO-LOCK WHERE <f1>=v1 AND <f2>=v2 NO-ERROR
    →  Optional<Tbl> result = repo.findByF1AndF2(v1, v2);
    ⚠  Map WHERE-clause fields 1-for-1 to the method's parameters.
       Do NOT invent parameters that are not in the WHERE clause.
  IF NOT AVAILABLE <tbl>                   →  if (result.isEmpty())
  IF AVAILABLE <tbl>                       →  if (result.isPresent())
  FOR EACH <tbl> NO-LOCK WHERE …           →  repo.findAll(spec)  or JPQL query
  EXCLUSIVE-LOCK                           →  @Transactional + optimistic lock or
                                              EntityManager.lock(entity, PESSIMISTIC_WRITE)
  BUFFER-COPY src EXCEPT f1 f2 TO dst      →  copy all fields except f1, f2 manually
  VALIDATE rec NO-ERROR / RELEASE rec      →  entityManager.persist/merge + flush

TRANSACTIONS
  DO TRANSACTION ON ERROR UNDO, THROW     →  @Transactional  (or programmatic
                                              TransactionTemplate with rollback on
                                              any RuntimeException)

FLOW CONTROL
  REPEAT … END                            →  while (true) { … }
  IF … THEN NEXT                          →  if (…) continue;
  LEAVE <label>                           →  break <label>;
  FOR EACH … : … END  (with block label)  →  labelled for loop

MISC
  ASSIGN f1 = v1 f2 = v2                  →  f1 = v1;  f2 = v2;
  RUN proc IN TARGET-PROCEDURE(…)         →  this.proc(…)  + TODO if unresolvable
  mipEnv:FormatMessage(…, "DESCRIPTION")  →  errorService.formatMessage(…)
  pfutils:isnull(x)  / pfutils:notnull(x) →  x == null  /  x != null
  {&ErrorStatus}                          →  (last operation threw an exception)
  {mip/inc/mipthrowerror.i …}             →  throw new AppException(code, message)
  {CatchError.i}                          →  } catch (Exception e) { throw e; }
                                             finally { /* FINALLY block content */ }
  Log("…")                                →  logger.info("…")
  NO-ERROR at end of statement            →  wrap in try/catch; set error flag
  DECIMAL(x)                              →  new BigDecimal(x.trim())
"""

# ── Single-file (small) conversion ───────────────────────────────────────────
SYSTEM_PROMPT = f"""\
You are an expert software engineer specialising in migrating legacy \
Progress OpenEdge ABL (4GL) code to modern Java 17.

Your task:
1. Convert the supplied Progress 4GL source file to idiomatic, \
production-quality Java 17.
2. Follow modern Java best practices: proper class structure, access \
modifiers, generics, streams, Optional, etc.
3. Apply the mapping table below exactly and completely:

{_CONSTRUCT_MAP}

4. Preserve all procedure, function, and method names exactly as they \
appear in the ABL source.  Only rename if the original name is a reserved \
Java keyword, in which case append an underscore (e.g. "class_").
5. For any construct that cannot be directly translated, add a \
// TODO: [reason] comment at the relevant line and continue with the \
best-effort translation.
6. Add a short Javadoc comment on every public method.
7. Output ONLY the raw Java source code — no markdown fences, \
no explanation text, no bullet-point summaries after the closing brace."""

# ── Per-chunk conversion (large-file pipeline) ────────────────────────────────
CHUNK_SYSTEM_PROMPT = f"""\
You are an expert software engineer specialising in migrating legacy \
Progress OpenEdge ABL (4GL) code to modern Java 17.

You are converting ONE CHUNK of a larger ABL file.  Shared global \
definitions from the same file are provided for context — do NOT \
re-declare them; they will appear as fields in the enclosing class.

Your task for this chunk:
1. Produce ONLY the body of one or more Java methods / inner classes \
that correspond to the ABL procedures or functions in this chunk.
2. Do NOT output a class declaration or import statements — those will \
be added by the merge step.
3. Follow modern Java 17 idioms (streams, records, Optional, var, etc.).
4. Apply the mapping table below exactly and completely:

{_CONSTRUCT_MAP}

5. Preserve procedure / function names exactly; only rename if the name \
is a reserved Java keyword (append an underscore in that case).
6. Add a Javadoc comment to every method.
7. For anything that cannot be directly translated, leave a \
// TODO: [reason] comment.
8. If the chunk contains ONLY variable declarations, include directives, \
or other preamble with no translatable procedures or functions, output \
EXACTLY this string (nothing else, no extra whitespace):
   /* no translatable procedures in this chunk */
9. Output ONLY raw Java method bodies — no markdown fences, \
no explanation text, no bullet-point summaries."""

# ── Merge (large-file pipeline) ───────────────────────────────────────────────
MERGE_SYSTEM_PROMPT = """\
You are an expert Java architect.

You will receive several Java method / inner-class snippets that were \
independently converted from Progress ABL chunks, plus a list of shared \
field declarations.

Your task:
1. Combine ALL snippets into ONE complete, compilable Java 17 class.
   ⚠  Every method present in the input snippets MUST appear in the output.
      Do not silently drop, stub, or summarise any method.
2. Choose an appropriate class name derived from the filename hint provided.
3. Add all necessary import statements at the top.
4. Declare the shared fields (provided) as private instance fields.
   If a shared field corresponds to a lookup-map temp-table \
(Map<BigDecimal,BigDecimal>), declare it as such.
5. De-duplicate any repeated helper methods or inner classes, \
keeping the most complete version.
6. Ensure consistent formatting and access modifiers throughout.
7. Omit snippets that contain ONLY the exact placeholder:
   /* no translatable procedures in this chunk */
8. Add a class-level Javadoc comment describing the overall purpose.
9. Output ONLY the raw Java source — no markdown fences, \
no explanation text, no bullet-point summaries after the closing brace."""