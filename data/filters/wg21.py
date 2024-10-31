#!/usr/bin/env python3

import datetime
import html
import os.path
import panflute as pf
import re

embedded_md = re.compile('@@(.*?)@@|@(.*?)@')
expos_name = re.compile('\$([\w\-\s]*?)\$')
stable_names = {}
current_pnum = {}
current_note = 0
current_example = 0
current_pnum_count = 0

def prepare(doc):
    date = doc.get_metadata('date')
    if date == 'today':
        doc.metadata['date'] = datetime.date.today().isoformat()

    doc.metadata['pagetitle'] = pf.convert_text(
        pf.Plain(*doc.metadata['title'].content),
        input_format='panflute',
        output_format='plain')

    datadir = doc.get_metadata('datadir')

    with open(os.path.join(datadir, 'annex-f'), 'r') as f:
        stable_names.update(line.rstrip().split(maxsplit=1) for line in f)

    def highlighting(output_format):
        return pf.convert_text(
            '`-`{.default}',
            output_format=output_format,
            extra_args=[
              '--highlight-style', os.path.join(datadir, 'syntax', 'wg21.theme'),
              '--template', os.path.join(datadir, 'templates', 'highlighting'),
              '--metadata', 'title="-"',
            ])

    doc.metadata['highlighting-macros'] = pf.MetaBlocks(
        pf.RawBlock(highlighting('latex'), 'latex'))
    doc.metadata['highlighting-css'] = pf.MetaBlocks(
        pf.RawBlock(highlighting('html'), 'html'))

def finalize(doc):
    def init_code_elems(elem, doc):
        if isinstance(elem, pf.Header) and doc.format == 'latex':
            elem.walk(lambda elem, doc:
                elem.classes.append('raw')
                if any(isinstance(elem, cls) for cls in [pf.Code, pf.CodeBlock])
                else None)

        # Mark code elements within colored divspan as default.
        if any(isinstance(elem, cls) for cls in [pf.Div, pf.Span]) and \
           any(cls in elem.classes for cls in ['add', 'rm', 'ednote']):
            elem.walk(lambda elem, doc:
                elem.classes.insert(0, 'default')
                if any(isinstance(elem, cls) for cls in [pf.Code, pf.CodeBlock])
                else None)

        if not any(isinstance(elem, cls) for cls in [pf.Code, pf.CodeBlock]):
            return None

        # As `walk` performs post-order traversal, this is
        # guaranteed to run before the 'raw' code path.
        if not elem.classes:
            if isinstance(elem, pf.Code):
                cls = doc.get_metadata('highlighting.inline-code', 'default')
            elif isinstance(elem, pf.CodeBlock):
                cls = doc.get_metadata('highlighting.code-block', 'default')
            elem.classes.append(cls)

    doc.walk(init_code_elems)

    def collect_code_elems(elem, doc):
        if not any(isinstance(elem, cls) for cls in [pf.Code, pf.CodeBlock]):
            return None

        if 'raw' in elem.classes:
            return None

        if not any(cls in elem.classes for cls in ['cpp', 'default', 'diff']):
            return None

        code_elems.append(elem)

    code_elems = []
    doc.walk(collect_code_elems)
    if not code_elems:
        return

    def intersperse(lst, item):
        result = [item] * (len(lst) * 2 - 1)
        result[0::2] = lst
        return result

    datadir = doc.get_metadata('datadir')
    text = pf.convert_text(
        intersperse(
            [pf.Plain(elem) if isinstance(elem, pf.Code) else elem for elem in code_elems],
            pf.Plain(pf.RawInline('---', doc.format))),
        input_format='panflute',
        output_format=doc.format,
        extra_args=['--syntax-definition', os.path.join(datadir, 'syntax', 'isocpp.xml')])

    # Workaround for https://github.com/jgm/skylighting/issues/91.
    if doc.format == 'latex':
        text = text.replace('<', '\\textless{}') \
                   .replace('>', '\\textgreater{}')

    if doc.format == 'latex':
        texts = text.split('\n\n---\n\n')
    elif doc.format == 'html':
        texts = text.split('\n---\n')

    assert(len(code_elems) == len(texts))

    def convert(elem, text):
        def repl2(match):
            if match.isspace():  # @  @
                return match

            result = convert.cache.get(match)
            if result is not None:
                return result

            if doc.format == 'latex':
                # Undo `escapeLaTeX` from https://github.com/jgm/skylighting
                match = match.replace('\\textbackslash{}', '\\') \
                             .replace('\\{', '{') \
                             .replace('\\}', '}') \
                             .replace('\\VerbBar{}', '|') \
                             .replace('\\_', '_') \
                             .replace('\\&', '&') \
                             .replace('\\%', '%') \
                             .replace('\\#', '#') \
                             .replace('\\textasciigrave{}', '`') \
                             .replace('\\textquotesingle{}', '\'') \
                             .replace('{-}', '-') \
                             .replace('\\textasciitilde{}', '~') \
                             .replace('\\^{}', '^')

                # Undo the workaround escaping.
                match = match.replace('\\textless{}', '<') \
                             .replace('\\textgreater{}', '>')
            elif doc.format == 'html':
                match = html.unescape(match)

            result = pf.convert_text(
                pf.Plain(*pf.convert_text(match)[0].content)
                    .walk(divspan, doc)
                    .walk(init_code_elems, doc),
                input_format='panflute',
                output_format=doc.format,
                extra_args=['--syntax-definition', os.path.join(datadir, 'syntax', 'isocpp.xml')])

            convert.cache[match] = result
            return result

        def repl(match_obj):
            groups = match_obj.groups()
            if not any(groups):
                return match_obj.group()

            group = groups[0]
            if group is not None:
                return embedded_md.sub(repl, repl2(group))

            group = groups[1]
            if group is not None:
                return repl2(group)

        def repl_expos(match_obj):
            match = match_obj[1]
            if not match or match.isspace():  # $  $
                return match
            if doc.format == 'latex':
                pf.debug('Exposition-only names in latex is totally untested')
                result = "\\textitalic{{{}}}".format(match)
            elif doc.format == 'html':
                result = '<em>{}</em>'.format(match)
            else:
                raise ValueError('Unsupported doc format for expos-name')
            return result

        if isinstance(elem, pf.Code):
            text = embedded_md.sub(repl, text)
            text = expos_name.sub(repl_expos, text)
            result = pf.RawInline(text, doc.format)
        elif isinstance(elem, pf.CodeBlock):
            text = embedded_md.sub(repl, text)
            text = expos_name.sub(repl_expos, text)
            result = pf.RawBlock(text, doc.format)

        if 'diff' not in elem.classes:
            return result

        # For HTML, this is handled via CSS in `data/templates/wg21.html`.
        command = '\\renewcommand{{\\{}}}[1]{{\\textcolor[HTML]{{{}}}{{#1}}}}'

        uc = command.format('NormalTok', doc.get_metadata('uccolor'))
        add = command.format('VariableTok', doc.get_metadata('addcolor'))
        rm = command.format('StringTok', doc.get_metadata('rmcolor'))

        if isinstance(elem, pf.Code):
            return pf.Span(
                pf.RawInline(uc, 'latex'),
                pf.RawInline(add, 'latex'),
                pf.RawInline(rm, 'latex'),
                result)
        elif isinstance(elem, pf.CodeBlock):
            return pf.Div(
                pf.RawBlock('{', 'latex'),
                pf.RawBlock(uc, 'latex'),
                pf.RawBlock(add, 'latex'),
                pf.RawBlock(rm, 'latex'),
                result,
                pf.RawBlock('}', 'latex'))

    convert.cache = {}

    def code_elem(elem, doc):
        if not any(isinstance(elem, cls) for cls in [pf.Code, pf.CodeBlock]):
            return None

        if 'raw' in elem.classes:
            return None

        if not any(cls in elem.classes for cls in ['cpp', 'default', 'diff']):
            return None

        return convert(*next(converted))

    converted = zip(code_elems, texts)
    doc.walk(code_elem)

def header(elem, doc):
    if not isinstance(elem, pf.Header):
        return None

    if elem.identifier == 'bibliography':
        elem.classes.remove('unnumbered')

    elem.content.append(
        pf.Link(url='#{}'.format(elem.identifier), classes=['self-link']))

def divspan(elem, doc):
    """
    Non-code diffs: `add` and `rm` are classes that can be added to
    a `Div` or a `Span`. `add` colors the text with `addcolor` and
    `rm` colors the text `rmcolor`. For `Span`s, `add` underlines
    and `rm` strikes out the text.

    # Example

    ## `Div`

    Unchanged portion

    ::: add
    New paragraph

    > Quotes

    More new paragraphs
    :::

    ## `Span`

    > The return type is `decltype(`_e_(`m`)`)` [for the first form]{.add}.
    """

    def _wrap(opening, closing):
        if isinstance(elem, pf.Div):
            if elem.content and isinstance(elem.content[0], pf.Para):
                elem.content[0].content.insert(0, opening)
            else:
                elem.content.insert(0, pf.Plain(opening))
            if elem.content and isinstance(elem.content[-1], pf.Para):
                elem.content[-1].content.append(closing)
            else:
                elem.content.append(pf.Plain(closing))
        elif isinstance(elem, pf.Span):
            elem.content.insert(0, opening)
            elem.content.append(closing)

    def _color(html_color):
        _wrap(pf.RawInline('{{\\color[HTML]{{{}}}'.format(html_color), 'latex'),
              pf.RawInline('}', 'latex'))
        elem.attributes['style'] = 'color: #{}'.format(html_color)

    def _nonnormative(name, number='?'):
        _wrap(pf.Span(pf.Str('[\xa0'), pf.Emph(pf.Str('{} {}:'.format(name.title(), number))), pf.Space),
              pf.Span(pf.Str(' —\xa0'), pf.Emph(pf.Str('end {}'.format(name.lower()))), pf.Str('\xa0]')))

    def _diff(color, latex_tag, html_tag):
        if isinstance(elem, pf.Span):
            def protect_code(elem, doc):
                if isinstance(elem, pf.Code):
                    return pf.Span(pf.RawInline('\\mbox{', 'latex'),
                                   elem,
                                   pf.RawInline('}', 'latex'))
            elem.walk(protect_code)
            _wrap(pf.RawInline('\\{}{{'.format(latex_tag), 'latex'),
                  pf.RawInline('}', 'latex'))
            _wrap(pf.RawInline('<{}>'.format(html_tag), 'html'),
                  pf.RawInline('</{}>'.format(html_tag), 'html'))
        _color(doc.get_metadata(color))

    def pnum():
        global current_pnum
        num = pf.stringify(elem)

        depth = num.count('.')
        parts = num.split('.')

        def reset_below(i):
            to_delete = [k for k in current_pnum if k > i]
            for k in to_delete:
                del current_pnum[k]

        # If we see a level N, always reset levels below it.
        reset_below(depth)

        for i in range(len(parts)):
            # placeholder pnum parts are expressed by #
            if parts[i] == '#':
                # replace placeholder by:
                # - last used value if this is not the last part
                # - last used value + 1 otherwise
                if i == depth:
                    pt = current_pnum.get(i, 0) + 1
                    parts[i] = str(pt)
                    current_pnum[i] = pt
                else:
                    pt = current_pnum.get(i)
                    if pt is None:
                      pf.debug('Missing current value for non-lowest-level placeholder in {}'.format(num))
                      pt = 1
                      current_pnum[i] = pt
                      reset_below(i)
                    parts[i] = str(pt)
            else:
                try:
                    val = int(parts[i])
                    if i not in current_pnum or current_pnum[i] != val:
                        current_pnum[i] = val
                        # When we see a new value at a level,
                        # reset everything below that level.
                        reset_below(i)
                except ValueError:
                  pass

        num = '.'.join(parts)

        if '.' in num:
            num = '({})'.format(num)

        global current_pnum_count
        current_pnum_count = current_pnum_count + 1

        if doc.format == 'latex':
            return pf.RawInline('\\pnum{{{}}}'.format(num), 'latex')
        elif doc.format == 'html':
            return pf.Span(
                pf.RawInline(f'<a class="marginalized" href="#pnum_{current_pnum_count}"'
                f' id="pnum_{current_pnum_count}">{num}</a>', 'html'),
                classes=['marginalizedparent'])

        return pf.Superscript(pf.Str(num))

    def example(number='?'): _nonnormative('example', number)
    def note(number='?'):    _nonnormative('note', number)
    def colornote(desc, color):
        _wrap(pf.Str("[ {}: ".format(desc)), pf.Str(' ]'))
        _color(color)

    def add(): _diff('addcolor', 'uline', 'ins')
    def rm():  _diff('rmcolor', 'sout', 'del')

    if isinstance(elem, pf.Header):
        # When entering a new section, reset all auto numbering.
        global current_pnum, current_example, current_note
        current_pnum = {}
        current_example = 0
        current_note = 0

    if not any(isinstance(elem, cls) for cls in [pf.Div, pf.Span]):
        return None

    if 'pnum' in elem.classes and isinstance(elem, pf.Span):
        return pnum()

    if 'sref' in elem.classes and isinstance(elem, pf.Span):
        target = pf.stringify(elem)
        number = stable_names.get(target)
        
        prefix = target.split(sep=':')[0]
        # If this is a table, figure, or equation, needs a bit of special handling.
        
        # Equations don't have their own pages so link to the parent. 
        # This assumes that eq:meow's parent is meow, which is true so far but might change...
        linktarget = f'{target[3:]}#{target}' if prefix == 'eq' else target
          
        link = pf.Link(
            pf.Str('[{}]'.format(target)),
            url='https://eel.is/c++draft/{}'.format(linktarget))

        prefixmap = {
          'tab' : 'Table',
          'fig' : 'Figure',
          'eq'  : 'Equation'
        }

        if number is not None:
            numprefix = prefixmap.get(prefix)
            if numprefix is not None:
              number = f'{numprefix} {number}'
            return pf.Span(pf.Str(number), pf.Space(), link)
        else:
            pf.debug('mpark/wg21: stable name', target, 'not found')
            return link

    for cls in elem.classes:
        if cls.startswith('note'):
            num = cls[4:]
            if num == '-':
                num = '?'
            elif num:
                try:
                    current_note = int(num)
                except ValueError:
                    pass
            else:
                current_note = current_note + 1
                num = str(current_note)
            note(num)
        elif cls.startswith('example'):
            num = cls[7:]
            if num == '-':
              num = '?'
            elif num:
                try:
                    current_example = int(num)
                except ValueError:
                    pass
            else:
                current_example = current_example + 1
                num = str(current_example)
            example(num)
        elif cls == 'ednote':
            colornote("Editor's note", '0000ff')
        elif cls == 'draftnote':
            colornote('Drafting note', '01796F')
        elif cls == 'draftnote-blue':
            colornote('Drafting note', '0000ff')
        else:
            continue
        break

    if isinstance(elem, pf.Span) and 'indel' in elem.classes:
      """
      [aaa<-bbb]{.indel} is [aaa]{.diffins} [bbb]{.diffdel}
      """
      to_ins = []
      to_del = []
      seen_sep = False
      def _append(e):
        if seen_sep:
          to_del.append(e)
        else:
          to_ins.append(e)
      for i in elem.content:
          if not isinstance(i, pf.Str) or '<-' not in i.text:
            _append(i)
          else:
            first, second = i.text.split('<-', maxsplit=1)
            if first:
              to_ins.append(pf.Str(text=first))
            if second:
              to_del.append(pf.Str(text=second))
            seen_sep = True

      content = []
      if to_ins:
        content.append(pf.Span(*to_ins, classes=['diffins']))
      if to_del:
        content.append(pf.Span(*to_del, classes=['diffdel']))

      if len(content) == 1:
        return content[0]
      else:
        return pf.Span(*content)

    diff_cls = next(iter(cls for cls in elem.classes if cls in {'add', 'rm'}), None)
    if diff_cls == 'add':  add()
    elif diff_cls == 'rm': rm()

def cmptable(table, doc):
    """
    Comparison Tables: Code blocks are the first-class entities that get added
    to the table. Each code block is pushed onto the current row.
    A horizontal rule (`---`) is used to move to the next row.

    In the first row, the last header (if any) leading upto the i'th
    code block is the header for the i'th column of the table.

    The last block quote (if any) is used as the caption.

    # Example

    ::: cmptable

    > compare inspect of unconstrained and constrained types

    ### Before
    ```cpp
    std::visit([&](auto&& x) {
      strm << "got auto: " << x;
    }, v);
    ```

    ### After
    ```cpp
    inspect (v) {
      <auto> x: strm << "got auto: " << x;
    }
    ```

    ---

    ```cpp
    std::visit([&](auto&& x) {
      using X = std::remove_cvref_t<decltype(x)>;
      if constexpr (C1<X>()) {
        strm << "got C1: " << x;
      } else if constexpr (C2<X>()) {
        strm << "got C2: " << x;
      }
    }, v);
    ```

    ```cpp
    inspect (v) {
      <C1> c1: strm << "got C1: " << c1;
      <C2> c2: strm << "got C2: " << c2;
    }
    ```

    :::

    # Generates

    Table: compare inspect of unconstrained and constrained types

    +------------------------------------------------+---------------------------------------------+
    | __Before__                                     | __After__                                   |
    +================================================+=============================================+
    | ```cpp                                         | ```cpp                                      |
    | std::visit([&](auto&& x) {                     | inspect (v) {                               |
    |   strm << "got auto: " << x;                   |   <auto> x: strm << "got auto: " << x;      |
    | }, v);                                         | }                                           |
    |                                                | ```                                         |
    +------------------------------------------------+---------------------------------------------+
    | std::visit([&](auto&& x) {                     | ```cpp                                      |
    |   using X = std::remove_cvref_t<decltype(x)>;  | inspect (v) {                               |
    |   if constexpr (C1<X>()) {                     |   <C1> c1: strm << "got C1: " << c1;        |
    |     strm << "got C1: " << x;                   |   <C2> c2: strm << "got C2: " << c2;        |
    |   } else if constexpr (C2<X>()) {              | }                                           |
    |     strm << "got C2: " << x;                   | ```                                         |
    |   }                                            |                                             |
    | }, v);                                         |                                             |
    +------------------------------------------------+---------------------------------------------+
    """

    if not isinstance(table, pf.Div):
        return None

    if not any(cls in table.classes for cls in ['cmptable', 'tonytable']):
        return None

    rows = []
    kwargs = {}

    headers = []
    widths = []
    examples = []

    header = pf.Null()
    caption = None
    width = 0

    first_row = True
    table.content.append(pf.HorizontalRule())

    def warn(elem):
        pf.debug('mpark/wg21:', type(elem), pf.stringify(elem, newlines=False),
                 'in a comparison table is ignored')

    for elem in table.content:
        if isinstance(elem, pf.Header):
            if not isinstance(header, pf.Null):
                warn(header)

            if first_row:
                header = pf.Plain(*elem.content)
                width = float(elem.attributes['width']) if 'width' in elem.attributes else 0
            else:
                warn(elem)
        elif isinstance(elem, pf.BlockQuote):
            if caption is not None:
                warn(caption)

            caption = elem
        elif isinstance(elem, pf.CodeBlock):
            if first_row:
                headers.append(header)
                widths.append(width)

                header = pf.Null()
                width = 0

            examples.append(elem)
        elif isinstance(elem, pf.HorizontalRule) and examples:
            first_row = False

            rows.append(pf.TableRow(*[pf.TableCell(example) for example in examples]))
            examples = []
        else:
            warn(elem)

    if not all(isinstance(header, pf.Null) for header in headers):
        kwargs['header'] = pf.TableRow(*[pf.TableCell(header) for header in headers])

    if caption is not None:
        kwargs['caption'] = caption.content[0].content

    kwargs['width'] = widths

    return pf.Table(*rows, **kwargs)

def table(elem, doc):
    if not isinstance(elem, pf.Table):
        return None

    def header(elem, doc):
        if not isinstance(elem, pf.Plain):
            return None

        return pf.Div(
            pf.Plain(pf.RawInline('\\centering', 'latex'),
                     pf.Strong(*elem.content)),
            attributes={'style': 'text-align:center'})

    if elem.header is not None:
        elem.header.walk(header)

if __name__ == '__main__':
  pf.run_filters([
      divspan,
      cmptable,
      # after `cmptable` because...
      header, # doesn't apply to the "headers" in comparison table.
      table,  # also applies to tables generated by `cmptable`.
  ], prepare, finalize)
