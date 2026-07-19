from ironsbot.services.ai.analysis_parser import (
    AnalyzeDescParser,
    DescLine,
)

DESC = (
    "[sprite name=dot4]自身作为首发精灵[color=#52a5f2]首次[/color]"
    "[color=#52a5f2][color=#57c975]出战时[/color]，令对手"
    "[color=#52a5f2]当回合[/color]无法[color=#52a5f2]主动切换[/color]精灵且50%"
    "[color=#52a5f2][color=#f35555][color=#52a5f2]驱逐[/color]对手（boss无效）"
    "|[sprite name=dot1]自身[color=#52a5f2]首次[/color]"
    "[color=#52a5f2][color=#57c975]出战后[/color]召唤"
    "[color=#f35555]辛[/color]，[color=#f35555]辛[/color]的初始体力等同于自身的最大体力"
    "|[sprite name=dot1][color=#57c975]回合开始时[/color]，若"
    "[color=#f35555]辛[/color]存活则自身依次[color=#52a5f2]执行[/color]"
    "[color=#52a5f2]以[/color]下效果："
    "|    [sprite name=dot1][color=#f35555]辛[/color]每损失20%的体力"
    "[color=#52a5f2]当回合[/color]自身造成的攻击伤害提升10%（boss有效）"
    "|    [sprite name=dot5]若自身处于异常状态，则令对手随机1个技能PP值归零（boss无效）"
    "|    [sprite name=dot5]若自身处于能力下降状态，则"
    "[color=#52a5f2]当回合[/color][color=#57c975]战斗阶段结束时[/color]附加对手最大体力1/4的"
    "[color=#52a5f2]百分比伤害[/color]（boss无效）"
    "|[sprite name=dot1]自身[color=#57c975][color=#57c975]被击败[/color]后[/color]，"
    "[color=#52a5f2]己方[/color]获得3回合的[color=#f35555]辛之印记[/color]"
    "|[sprite name=dot4][color=#52a5f2]己方[/color]每阵亡1只精灵自身6%闪避对手的技能，"
    "对手为[color=#57c975][color=#f35555]英雄圣殿成员[/color]时闪避率翻倍（boss无效）"
)


class TestLineCount:
    def test_total_lines(self):
        parser = AnalyzeDescParser(DESC)
        assert len(parser.lines) == 8


class TestSprites:
    def test_all_sprites(self):
        parser = AnalyzeDescParser(DESC)
        assert parser.sprites == {"dot1", "dot4", "dot5"}

    def test_lines_by_sprite(self):
        parser = AnalyzeDescParser(DESC)
        assert len(parser.lines_by_sprite("dot4")) == 2
        assert len(parser.lines_by_sprite("dot1")) == 4
        assert len(parser.lines_by_sprite("dot5")) == 2

    def test_sprite_per_line(self):
        parser = AnalyzeDescParser(DESC)
        expected_sprites = [
            "dot4",
            "dot1",
            "dot1",
            "dot1",
            "dot5",
            "dot5",
            "dot1",
            "dot4",
        ]
        for line, expected in zip(parser.lines, expected_sprites):
            assert line.sprite == expected


class TestIndent:
    def test_top_level_lines_no_indent(self):
        parser = AnalyzeDescParser(DESC)
        for i in (0, 1, 2, 6, 7):
            assert parser.lines[i].indent == 0

    def test_sub_items_indented(self):
        parser = AnalyzeDescParser(DESC)
        for i in (3, 4, 5):
            assert parser.lines[i].indent == 4


class TestColors:
    def test_all_colors(self):
        parser = AnalyzeDescParser(DESC)
        assert parser.colors == {"#52a5f2", "#57c975", "#f35555"}


class TestPlainText:
    def test_first_line(self):
        parser = AnalyzeDescParser(DESC)
        assert parser.lines[0].plain_text == (
            "自身作为首发精灵首次出战时，令对手当回合无法主动切换精灵且50%驱逐对手（boss无效）"
        )

    def test_plain_text_no_indent(self):
        """plain_text 不应包含行首缩进空格"""
        parser = AnalyzeDescParser(DESC)
        assert not parser.lines[4].plain_text.startswith(" ")

    def test_sub_item_plain_text(self):
        parser = AnalyzeDescParser(DESC)
        assert (
            parser.lines[4].plain_text
            == "若自身处于异常状态，则令对手随机1个技能PP值归零（boss无效）"
        )


class TestMultiColor:
    """测试多颜色嵌套：同一个 [/color] 闭合多个标签时，文本应关联所有活跃颜色"""

    def test_dual_color_segment(self):
        """[color=#52a5f2][color=#57c975]出战时[/color] 应同时关联两种颜色"""
        parser = AnalyzeDescParser(DESC)
        line0 = parser.lines[0]
        segment = next(s for s in line0.segments if "出战时" in s.text)
        assert "#52a5f2" in segment.colors
        assert "#57c975" in segment.colors

    def test_triple_nested_colors(self):
        """[color=#52a5f2][color=#f35555][color=#52a5f2]驱逐[/color] 应同时关联蓝/红两种颜色"""
        parser = AnalyzeDescParser(DESC)
        line0 = parser.lines[0]
        segment = next(s for s in line0.segments if s.text == "驱逐")
        assert set(segment.colors) == {"#52a5f2", "#f35555"}

    def test_colored_texts_matches_multi(self):
        """colored_texts 应在多颜色片段中也能命中"""
        parser = AnalyzeDescParser(DESC)
        line0 = parser.lines[0]
        blue_texts = line0.colored_texts("#52a5f2")
        assert "出战时" in "".join(blue_texts)
        green_texts = line0.colored_texts("#57c975")
        assert "出战时" in "".join(green_texts)

    def test_last_line_dual_color(self):
        """最后一行 [color=#57c975][color=#f35555]英雄圣殿成员[/color]"""
        parser = AnalyzeDescParser(DESC)
        line7 = parser.lines[7]
        segment = next(s for s in line7.segments if "英雄圣殿成员" in s.text)
        assert "#57c975" in segment.colors
        assert "#f35555" in segment.colors


class TestBatchClose:
    """回归测试：连续打开的多个 [color] 应被单个 [/color] 一并关闭"""

    def test_red_does_not_leak_after_close(self):
        """'驱逐' 后的 '对手（boss无效）' 不应携带 #f35555"""
        parser = AnalyzeDescParser(DESC)
        line0 = parser.lines[0]
        seg = next(s for s in line0.segments if "对手（boss无效）" in s.text)
        assert "#f35555" not in seg.colors

    def test_styled_html_does_not_leak(self):
        """用 #f35555 工厂函数渲染时，'对手（boss无效）' 不应被包裹"""
        parser = AnalyzeDescParser(DESC)
        styles = {"#f35555": lambda t: f"<b>{t}</b>"}
        html = parser.lines[0].to_html(styles)
        assert "<b>对手（boss无效）</b>" not in html
        assert "对手（boss无效）" in html


class TestColoredTexts:
    def test_red_names_in_line1(self):
        parser = AnalyzeDescParser(DESC)
        line1 = parser.lines[1]
        reds = line1.colored_texts("#f35555")
        assert reds == ["辛", "辛"]

    def test_no_color_segments(self):
        """无颜色片段不应出现在 colored_texts 结果中"""
        parser = AnalyzeDescParser(DESC)
        line4 = parser.lines[4]
        assert line4.colored_texts("#52a5f2") == []
        assert line4.colored_texts("#f35555") == []


class TestToHtml:
    def test_no_styles_returns_plain(self):
        parser = AnalyzeDescParser(DESC)
        result = parser.lines[4].to_html()
        assert "<" not in result
        assert result == "若自身处于异常状态，则令对手随机1个技能PP值归零（boss无效）"

    def test_single_color_style(self):
        parser = AnalyzeDescParser(DESC)
        styles = {"#f35555": lambda t: f"<b>{t}</b>"}
        line1_html = parser.lines[1].to_html(styles)
        assert "<b>辛</b>" in line1_html
        assert "自身" in line1_html
        assert "<b>自身" not in line1_html

    def test_multi_color_nesting(self):
        """多颜色片段应嵌套应用所有匹配的工厂函数"""
        parser = AnalyzeDescParser(DESC)
        styles = {
            "#52a5f2": lambda t: f'<span class="blue">{t}</span>',
            "#57c975": lambda t: f'<span class="green">{t}</span>',
        }
        line0_html = parser.lines[0].to_html(styles)
        assert 'class="blue"' in line0_html
        assert 'class="green"' in line0_html
        assert "出战时" in line0_html

    def test_duplicate_color_in_stack_applied_once(self):
        """颜色栈中重复的颜色，工厂函数只应用一次"""
        parser = AnalyzeDescParser(DESC)
        call_count = 0

        def counting_styler(t: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"<b>{t}</b>"

        styles = {"#52a5f2": counting_styler}
        line0 = parser.lines[0]
        seg = next(s for s in line0.segments if s.text == "驱逐")
        DescLine(segments=[seg]).to_html(styles)
        assert call_count == 1

    def test_full_html_with_separator(self):
        parser = AnalyzeDescParser(DESC)
        styles = {"#f35555": lambda t: f"<b>{t}</b>"}
        full = parser.to_html(styles, line_separator="\n")
        lines = full.split("\n")
        assert len(lines) == 8

    def test_html_escapes_text(self):
        """含 HTML 特殊字符的文本应被转义"""
        p = AnalyzeDescParser("体力>50%时[color=#52a5f2]攻击<防御[/color]")
        styles = {"#52a5f2": lambda t: f"<em>{t}</em>"}
        result = p.lines[0].to_html(styles)
        assert "体力&gt;50%时" in result
        assert "<em>攻击&lt;防御</em>" in result


DESC_WITH_ID = (
    "[sprite name=dot1][color=#52a5f2]首次[/color]"
    "[color=#52a5f2]出战(491)[/color]"
    "[color=#57c975]登场时[/color]获得4层[color=#f35555]自然祝福[/color]，"
    "[color=#52a5f2]之后[/color]每次[color=#57c975]登场[/color]时获得2层自然祝福"
    "|[sprite name=dot1][color=#57c975]战斗阶段结束时[/color]，若"
    "[color=#52a5f2]当回合(412)[/color]自身使用了技能则消耗1层"
    "[color=#f35555]自然祝福[/color]，若"
    "[color=#52a5f2]当回合(412)[/color]自身未使用技能则获得1层"
    "[color=#f35555]自然祝福[/color]"
)


class TestSegmentId:
    def test_id_extracted(self):
        """'出战(491)' 应提取 id=491"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        seg = next(s for s in parser.segments if s.text == "出战")
        assert seg.id == 491

    def test_id_stripped_from_text(self):
        """提取 ID 后文本不应包含 '(491)'"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        seg = next(s for s in parser.segments if s.id == 491)
        assert "(491)" not in seg.text
        assert seg.text == "出战"

    def test_multiple_same_id(self):
        """同一描述中多次出现的相同 ID 应分别提取"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        segs_412 = [s for s in parser.segments if s.id == 412]
        assert len(segs_412) == 2
        assert all(s.text == "当回合" for s in segs_412)

    def test_segments_with_id_property(self):
        """segments_with_id 应返回所有出现的 ID"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        assert parser.segments_with_id == {491, 412}

    def test_no_id_segments_are_none(self):
        """无 ID 的片段 id 应为 None"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        seg = next(s for s in parser.segments if s.text == "首次")
        assert seg.id is None

    def test_plain_text_excludes_id(self):
        """纯文本输出不应包含括号内的 ID"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        plain = parser.lines[0].plain_text
        assert "(491)" not in plain
        assert "出战" in plain

    def test_html_excludes_id(self):
        """HTML 输出不应包含括号内的 ID"""
        parser = AnalyzeDescParser(DESC_WITH_ID)
        styles = {"#52a5f2": lambda t: f"<b>{t}</b>"}
        result = parser.lines[0].to_html(styles)
        assert "(491)" not in result
        assert "<b>出战</b>" in result

    def test_full_width_parens_not_treated_as_id(self):
        """全角括号（数字）不应被当作 ID 提取"""
        parser = AnalyzeDescParser(DESC)
        plain = parser.to_plain_text()
        assert "（boss无效）" in plain
