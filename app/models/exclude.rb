class Exclude < ApplicationRecord
	belongs_to :request

	def self.delete_excludes(excludes_array)
		excludes_array.each do |exclude|
			self.find(exclude).destroy
		end
	end

end
