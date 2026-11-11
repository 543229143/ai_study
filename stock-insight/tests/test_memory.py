from core.memory import StockMemory


def test_watchlist_roundtrip(tmp_path):
    memory = StockMemory(data_dir=str(tmp_path))
    assert "为空" in memory.get_watchlist()

    memory.add_watchlist("600519|贵州茅台")
    assert "600519" in memory.get_watchlist()

    # 重复添加不应产生两条
    memory.add_watchlist("600519|贵州茅台")
    assert memory.get_watchlist().count("600519") == 1

    memory.remove_watchlist("600519")
    assert "为空" in memory.get_watchlist()


def test_analysis_history_persists(tmp_path):
    memory = StockMemory(data_dir=str(tmp_path))
    memory.save_analysis("600519|分析茅台|偏多")
    memory.save_analysis("600519|再分析|观望")

    history = memory.get_history("600519")
    assert "偏多" in history
    assert "观望" in history
    assert "无历史" in memory.get_history("000001")


def test_preferences_roundtrip(tmp_path):
    memory = StockMemory(data_dir=str(tmp_path))
    memory.set_preference("risk=conservative")
    assert "conservative" in memory.get_preferences()
