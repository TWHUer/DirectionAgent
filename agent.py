from agent_network.base import BaseAgent
     
    
class DirectionAgent(BaseAgent):
    def __init__(self, graph, config, logger):
        super().__init__(graph, config, logger)
        
    def forward(self, messages, **kwargs):

        import json

        task = kwargs.get("task")  # 获取任务信息，例如："从北京到上海"

        if not task:
            print("Error: Task is not provided!")
            return None, None  # 或者 raise ValueError("Task is required")

        # 构造 prompt（明确要求返回 JSON）
        prompt = f"""
        请从以下文本中提取出发地和目的地，并返回一个 JSON 对象，包含 `start_address` 和 `end_address` 字段：

        文本内容：{task}

        要求：
        1. 只返回 JSON 格式数据，不要包含任何额外文本或 Markdown 代码块。
        2. 如果没有明确的出发地或目的地，对应字段设为 `null`。
        3. 示例正确返回格式：
        {{"start_address": "北京", "end_address": "上海"}}
        """

        # 使用 add_message 添加对话（假设 self.add_message 是 agent_network 提供的方法）
        self.add_message("system", "你是一个地址提取助手，必须严格返回 JSON 格式数据。", messages)
        self.add_message("user", prompt, messages)

        # 调用 DeepSeek API（注意修改 base_url 和 model）
        response = self.chat_llm(
            messages,
            api_key="sk-ca3583e3026949299186dcbf3fc34f8c",  # 替换成你的 DeepSeek API Key
            base_url="https://api.deepseek.com/v1",  # DeepSeek 的 API 地址
            model="deepseek-chat",  # 或其他支持的模型，如 deepseek-chat-32k
            response_format={"type": "json_object"}  # 强制返回 JSON
        )

        # 解析返回的 JSON
        try:
            response_data = response.content
            if isinstance(response_data, str):
                response_data = json.loads(response_data)  # 确保是 dict
            
            start_address = response_data.get("start_address")
            end_address = response_data.get("end_address")
            print(f"解析成功: 出发地={start_address}, 目的地={end_address}")
        except Exception as e:
            print(f"解析失败: {e}")
            print("API 返回的原始数据:", response.content)
            return None, None

        if not start_address or not end_address:
            error_msg = "必须提供起点(start_address)和终点(end_address)"
            return {"result": f"错误: {error_msg}"}

        try:
            import requests
            from geopy.geocoders import Photon

            # 1. 地理编码
            geolocator = Photon(
                user_agent="nav_tool_final_v2",
                domain="photon.komoot.io",
                timeout=10
            )
            
            # 获取坐标
            start_loc = geolocator.geocode(f"{start_address}", timeout=10)
            end_loc = geolocator.geocode(f"{end_address}", timeout=10)
            
            if not start_loc or not end_loc:
                return {"result": "错误: 地址解析失败"}

            # 2. 获取路径数据
            base_url = "http://router.project-osrm.org/route/v1/driving"
            coords_str = f"{start_loc.longitude},{start_loc.latitude};{end_loc.longitude},{end_loc.latitude}"
            response = requests.get(
                f"{base_url}/{coords_str}",
                params={
                    "overview": "full",
                    "geometries": "polyline",
                    "steps": "true",
                    "annotations": "true"
                },
                timeout=15
            )
            
            route_data = response.json()

            # 3. 验证数据
            if not route_data.get("routes"):
                return {"result": "错误: 未找到有效路径"}

            # 4. 构建结果字符串
            result_str = self._build_result_string(
                start_address, 
                end_address,
                start_loc,
                end_loc,
                route_data
            )
            
            return {"result": result_str}

        except requests.exceptions.RequestException:
            return {"result": "错误: 网络请求失败"}
        except Exception as e:
            return {"result": f"错误: {str(e)}"}

    def _build_result_string(self, start_addr, end_addr, start_loc, end_loc, route_data):
        """构建包含完整转向信息的字符串结果"""
        main_route = route_data["routes"][0]
        leg = main_route["legs"][0]
        
        # 基本信息
        lines = [
            "=== 导航路线 ===",
            f"起点: {start_addr} (坐标: {start_loc.longitude:.6f}, {start_loc.latitude:.6f})",
            f"终点: {end_addr} (坐标: {end_loc.longitude:.6f}, {end_loc.latitude:.6f})",
            f"总距离: {main_route['distance']/1000:.1f}公里",
            f"预计时间: {main_route['duration']/60:.1f}分钟",
            "\n=== 详细转向指引 ==="
        ]
        
        # 转向统计
        turn_stats = {
            "right": 0,
            "left": 0,
            "slight_right": 0,
            "slight_left": 0,
            "uturn": 0
        }
        
        # 转向步骤
        for i, step in enumerate(leg["steps"], 1):
            maneuver = step.get("maneuver", {})
            instruction = maneuver.get("instruction", "继续前行")
            modifier = maneuver.get("modifier", "")
            
            # 统计转向类型
            if modifier in turn_stats:
                turn_stats[modifier] += 1
                prefix = {
                    "right": "【右转】",
                    "left": "【左转】", 
                    "slight_right": "【轻微右转】",
                    "slight_left": "【轻微左转】",
                    "uturn": "【掉头】"
                }.get(modifier, "")
                instruction = f"{prefix}{instruction}"
            
            lines.append(
                f"{i}. {instruction} "
                f"(距离: {step['distance']}米, "
                f"时间: {step['duration']}秒)"
            )
        
        # 转向统计摘要
        lines.extend([
            "\n=== 转向统计 ===",
            f"• 右转: {turn_stats['right']}次",
            f"• 左转: {turn_stats['left']}次",
            f"• 轻微右转: {turn_stats['slight_right']}次",
            f"• 轻微左转: {turn_stats['slight_left']}次",
            f"• 掉头: {turn_stats['uturn']}次",
            f"• 总计: {sum(turn_stats.values())}次转向"
        ])
        
        return "\n".join(lines)