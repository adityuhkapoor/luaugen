--!strict
-- Example evaluator for the generated BlendSpaces table.
-- evaluate(data, spaceName, value) -> { a = clip, b = clip?, weight = number }

local Blend1D = {}

function Blend1D.evaluate(data, spaceName: string, value: number)
	local space = data[spaceName]
	assert(space, "unknown blend space " .. tostring(spaceName))
	assert(type(value) == "number" and value == value, "value must be a number")
	local positions, clips = space.positions, space.clips
	local n = #positions
	if value <= positions[1] then
		return { a = clips[1], weight = 0 }
	end
	if value >= positions[n] then
		return { a = clips[n], weight = 0 }
	end
	for i = 1, n - 1 do
		local lo, hi = positions[i], positions[i + 1]
		if value >= lo and value < hi then
			return { a = clips[i], b = clips[i + 1], weight = (value - lo) / (hi - lo) }
		end
	end
	error("unreachable")
end

return Blend1D
